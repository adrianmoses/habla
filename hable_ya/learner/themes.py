"""Per-band conversational scenarios and cooldown-aware selection.

Each `Theme` is a scenario the tutor can drive: a human-readable `domain`,
a 1–2 sentence Spanish prompt telling the model what situation to stage,
and a list of grammatical `target_structures` the scenario naturally
elicits at that CEFR band.

`get_session_theme` picks one from the current band's pool, skipping any
whose domain appears in the last ``theme_cooldown`` sessions (default 3,
configured via settings), and falls back to the neutral theme only if the
pool is exhausted by the cooldown — which, at ≥ 8 entries per band, cannot
happen under default settings.
"""

from __future__ import annotations

import random

from eval.fixtures.schema import CEFRBand, Theme

NEUTRAL_THEME = Theme(
    domain="conversación abierta",
    prompt=(
        "Mantén una conversación natural con el estudiante. Deja que el "
        "estudiante elija el tema; si no propone uno, empieza con algo "
        "cotidiano (su día, familia, planes, algo que le guste)."
    ),
    target_structures=[],
)


_A1_THEMES: list[Theme] = [
    Theme(
        domain="presentarse",
        prompt=(
            "El estudiante se presenta por primera vez. Tú eres un compañero "
            "nuevo en clase — saluda y pregúntale su nombre, de dónde es, y "
            "qué idiomas habla. Haz una sola pregunta a la vez."
        ),
        target_structures=["ser / llamarse", "de + país", "hablar + idioma"],
    ),
    Theme(
        domain="pedir un café",
        prompt=(
            "El estudiante entra en una cafetería. Tú eres el camarero — "
            "saluda, pregúntale qué quiere tomar y si lo quiere para aquí "
            "o para llevar. Mantén frases cortas."
        ),
        target_structures=[
            "querer + sustantivo",
            "saludos formales",
            "para aquí / para llevar",
        ],
    ),
    Theme(
        domain="hablar de la familia",
        prompt=(
            "Pregúntale al estudiante por su familia: cuántos hermanos tiene, "
            "cómo se llaman, a qué se dedican. Tú puedes comentar brevemente "
            "sobre la tuya para modelar la estructura."
        ),
        target_structures=["tener + número", "posesivos mi/tu", "verbos en presente"],
    ),
    Theme(
        domain="los números y la hora",
        prompt=(
            "Ayuda al estudiante a practicar números y la hora. Pregúntale "
            "qué hora es, a qué hora se levanta, cuántos años tiene, su "
            "número de teléfono."
        ),
        target_structures=["ser + hora", "números 0-100", "a qué hora + verbo"],
    ),
    Theme(
        domain="comprar en el mercado",
        prompt=(
            "El estudiante está en un mercado comprando fruta. Tú eres el "
            "vendedor — ofrece lo que tienes, pregúntale cuánto quiere, y "
            "dile el precio. Usa kilos y euros."
        ),
        target_structures=[
            "querer + cantidad + de",
            "cuánto cuesta / vale",
            "números grandes",
        ],
    ),
    Theme(
        domain="pedir direcciones",
        prompt=(
            "El estudiante está perdido y busca la estación de metro. Tú "
            "eres un peatón amable — dale indicaciones sencillas: sigue "
            "recto, gira a la derecha, está al lado de."
        ),
        target_structures=[
            "imperativo informal (sigue, gira)",
            "preposiciones de lugar",
            "estar + ubicación",
        ],
    ),
    Theme(
        domain="hablar del clima",
        prompt=(
            "Comenta el tiempo con el estudiante: cómo está hoy, qué tiempo "
            "hace en su ciudad, qué estación prefiere. Frases muy cortas, "
            "vocabulario básico."
        ),
        target_structures=[
            "hace + sustantivo (frío/calor/sol)",
            "estar + adjetivo (soleado/nublado)",
            "estaciones",
        ],
    ),
    Theme(
        domain="mi día normal",
        prompt=(
            "Pregúntale al estudiante por su rutina diaria: a qué hora se "
            "levanta, qué desayuna, a qué hora trabaja o estudia. Reacciona "
            "con comentarios cortos."
        ),
        target_structures=[
            "verbos reflexivos en presente (levantarse, ducharse)",
            "a qué hora + verbo",
            "primero / después / luego",
        ],
    ),
    Theme(
        domain="comida favorita",
        prompt=(
            "Habla con el estudiante sobre comida: qué le gusta comer, qué "
            "no le gusta, cuál es su plato favorito. Nombra platos típicos "
            "españoles o latinoamericanos si ayuda."
        ),
        target_structures=[
            "gustar + sustantivo",
            "preferir + sustantivo",
            "comidas básicas",
        ],
    ),
    Theme(
        domain="colores y ropa",
        prompt=(
            "Describe con el estudiante la ropa que lleva hoy: colores, "
            "prendas, si le queda bien. Si no sabe una palabra, ofrécesela "
            "de forma natural."
        ),
        target_structures=[
            "llevar + prenda",
            "colores + concordancia",
            "me queda / te queda",
        ],
    ),
]


_A2_THEMES: list[Theme] = [
    Theme(
        domain="planes para el fin de semana",
        prompt=(
            "Pregúntale al estudiante qué va a hacer este fin de semana: si "
            "tiene planes con amigos, si va a salir, qué le gustaría hacer. "
            "Comparte los tuyos brevemente."
        ),
        target_structures=[
            "ir a + infinitivo",
            "me gustaría + infinitivo",
            "quedar con alguien",
        ],
    ),
    Theme(
        domain="describir tu ciudad",
        prompt=(
            "Pídele al estudiante que describa la ciudad donde vive: cómo "
            "es, qué hay de interesante, qué le gusta y qué no. Reacciona "
            "haciendo preguntas de seguimiento."
        ),
        target_structures=["hay / no hay", "es + adjetivo", "se puede + infinitivo"],
    ),
    Theme(
        domain="en el restaurante",
        prompt=(
            "Estás atendiendo al estudiante en un restaurante. Pregúntale "
            "qué va a tomar, explícale algunos platos de la carta, y "
            "recomiéndale uno si te pide sugerencia."
        ),
        target_structures=[
            "de primero / de segundo",
            "llevar + ingredientes",
            "recomendar + sustantivo",
        ],
    ),
    Theme(
        domain="viajar en tren o autobús",
        prompt=(
            "El estudiante quiere comprar un billete. Tú eres la persona en "
            "la taquilla — pregúntale destino, si es ida y vuelta, a qué "
            "hora quiere salir."
        ),
        target_structures=[
            "ida / ida y vuelta",
            "a qué hora sale / llega",
            "hacer trasbordo",
        ],
    ),
    Theme(
        domain="ir al médico",
        prompt=(
            "El estudiante tiene una cita médica. Tú eres el médico — "
            "pregúntale qué le pasa, desde cuándo, si tiene otros síntomas. "
            "Dale un consejo sencillo al final."
        ),
        target_structures=[
            "me duele / me duelen",
            "desde hace + tiempo",
            "tener que + infinitivo",
        ],
    ),
    Theme(
        domain="vacaciones pasadas",
        prompt=(
            "Pregúntale al estudiante por sus últimas vacaciones: adónde "
            "fue, con quién, qué hizo, si le gustó. Practica pretéritos."
        ),
        target_structures=[
            "pretérito indefinido (fui, estuve, vi)",
            "estar + gerundio en pasado",
            "me gustó / no me gustó",
        ],
    ),
    Theme(
        domain="llamar por teléfono",
        prompt=(
            "El estudiante llama a un restaurante para reservar mesa. Tú "
            "contestas el teléfono — pídele nombre, día, hora, número de "
            "personas."
        ),
        target_structures=[
            "a nombre de",
            "para + número de personas",
            "cortesía formal en teléfono",
        ],
    ),
    Theme(
        domain="alquilar un piso",
        prompt=(
            "El estudiante busca piso y te llama por un anuncio. Tú eres el "
            "propietario — descríbele el piso, dile el precio, y quedad "
            "para verlo."
        ),
        target_structures=[
            "tener + habitaciones",
            "estar + ubicación",
            "quedar para + infinitivo",
        ],
    ),
    Theme(
        domain="contar una rutina diaria",
        prompt=(
            "El estudiante te cuenta su rutina con más detalle: qué hace "
            "por la mañana, por la tarde, por la noche. Pide que añada "
            "adverbios de frecuencia."
        ),
        target_structures=[
            "adverbios de frecuencia (siempre, a veces, nunca)",
            "soler + infinitivo",
            "partes del día",
        ],
    ),
    Theme(
        domain="hablar del trabajo actual",
        prompt=(
            "Habla con el estudiante sobre su trabajo o sus estudios: qué "
            "hace, desde hace cuánto, qué le gusta y qué le cuesta."
        ),
        target_structures=[
            "trabajar de / como",
            "llevar + tiempo + gerundio",
            "me cuesta + infinitivo",
        ],
    ),
]


_B1_THEMES: list[Theme] = [
    Theme(
        domain="experiencia inolvidable",
        prompt=(
            "Pídele al estudiante que te cuente una experiencia que nunca "
            "olvidará: cuándo pasó, dónde, qué hizo especial ese momento. "
            "Practica narración en pasado."
        ),
        target_structures=[
            "contraste pretérito / imperfecto",
            "cuando + pretérito",
            "adjetivos de valoración",
        ],
    ),
    Theme(
        domain="problema en el trabajo",
        prompt=(
            "El estudiante te cuenta un problema reciente en el trabajo. "
            "Escucha, pregúntale qué hizo, y sugiérele una alternativa con "
            "'yo que tú' o 'deberías'."
        ),
        target_structures=[
            "yo que tú + condicional",
            "deberías + infinitivo",
            "porque / aunque",
        ],
    ),
    Theme(
        domain="tu vida hace diez años",
        prompt=(
            "Habla con el estudiante de cómo era su vida hace diez años: "
            "dónde vivía, qué hacía, con quién salía. Foco en el imperfecto."
        ),
        target_structures=[
            "imperfecto descriptivo",
            "antes + imperfecto / ahora + presente",
            "soler + infinitivo en pasado",
        ],
    ),
    Theme(
        domain="planear un viaje con amigos",
        prompt=(
            "Planead juntos un viaje ficticio: adónde iréis, cuándo, qué "
            "haréis allí, quién reserva qué. Usa futuro y presente de "
            "intención."
        ),
        target_structures=[
            "futuro simple",
            "subjuntivo en 'cuando + verbo'",
            "reparto de tareas",
        ],
    ),
    Theme(
        domain="consejos sobre salud",
        prompt=(
            "El estudiante te pide consejo porque está estresado / cansado. "
            "Dale recomendaciones concretas con imperativo o 'te recomiendo "
            "que + subjuntivo'."
        ),
        target_structures=[
            "te recomiendo que + subjuntivo",
            "imperativo afirmativo/negativo",
            "es importante que + subjuntivo",
        ],
    ),
    Theme(
        domain="película o libro que te marcó",
        prompt=(
            "Pide al estudiante que te hable de una película o un libro "
            "que le marcó: de qué va, qué le gustó, por qué. Reacciona con "
            "opiniones propias."
        ),
        target_structures=[
            "tratar de / ir de",
            "lo que más / menos me gustó",
            "creer que + indicativo / no creer que + subjuntivo",
        ],
    ),
    Theme(
        domain="problemas con un electrodoméstico",
        prompt=(
            "Al estudiante se le ha roto la lavadora. Tú eres el servicio "
            "técnico — pregúntale qué pasa, desde cuándo, y propón una "
            "solución."
        ),
        target_structures=[
            "se me ha roto / estropeado",
            "pretérito perfecto",
            "tiene que + infinitivo",
        ],
    ),
    Theme(
        domain="buscar trabajo",
        prompt=(
            "Simula una entrevista de trabajo informal: pregunta al "
            "estudiante por su experiencia, sus puntos fuertes, por qué "
            "le interesa el puesto."
        ),
        target_structures=[
            "llevar + tiempo + gerundio",
            "haber + participio",
            "me interesa + infinitivo / sustantivo",
        ],
    ),
    Theme(
        domain="redes sociales en tu vida",
        prompt=(
            "Habla con el estudiante de cómo usa las redes sociales: "
            "cuáles usa, para qué, si ha tenido alguna experiencia mala. "
            "Comparte tu opinión."
        ),
        target_structures=[
            "para + infinitivo",
            "desde que + indicativo",
            "valoraciones personales",
        ],
    ),
    Theme(
        domain="un malentendido reciente",
        prompt=(
            "Pídele al estudiante que te cuente un malentendido reciente "
            "con alguien: qué pasó, cómo lo solucionó, qué aprendió."
        ),
        target_structures=[
            "pluscuamperfecto",
            "si hubiera sabido… (introducir)",
            "al final + pretérito",
        ],
    ),
]


_B2_THEMES: list[Theme] = [
    Theme(
        domain="impacto del teletrabajo",
        prompt=(
            "Debate con el estudiante los efectos del teletrabajo en la "
            "vida personal y profesional. Pide argumentos concretos y "
            "matiza si estás de acuerdo."
        ),
        target_structures=[
            "conectores de causa/consecuencia",
            "aunque + indicativo/subjuntivo",
            "estoy de acuerdo en que / con que",
        ],
    ),
    Theme(
        domain="decisión difícil",
        prompt=(
            "El estudiante te cuenta una decisión difícil que tomó o que "
            "debe tomar. Ayúdale a ordenar pros y contras, y reflexionad "
            "sobre el condicional."
        ),
        target_structures=[
            "condicional simple / compuesto",
            "si + imperfecto de subjuntivo + condicional",
            "por un lado / por otro lado",
        ],
    ),
    Theme(
        domain="debate sobre dietas y salud",
        prompt=(
            "Debatid sobre distintas dietas (vegetariana, mediterránea, "
            "keto…). Pide al estudiante que defienda una posición y "
            "rebátele con respeto."
        ),
        target_structures=[
            "verbos de opinión + subjuntivo / indicativo",
            "a mi modo de ver",
            "aunque + subjuntivo",
        ],
    ),
    Theme(
        domain="tecnología y privacidad",
        prompt=(
            "Conversa sobre hasta qué punto ceder datos a las apps es un "
            "buen intercambio. Pide ejemplos concretos y contraargumenta."
        ),
        target_structures=[
            "voz pasiva refleja (se cede, se recoge)",
            "siempre que + subjuntivo",
            "conectores concesivos",
        ],
    ),
    Theme(
        domain="conflicto entre amigos o familia",
        prompt=(
            "El estudiante te cuenta un conflicto entre amigos o familiares. "
            "Ayúdale a verbalizarlo sin tomar partido y explora qué haría "
            "en el lugar del otro."
        ),
        target_structures=[
            "en su lugar + condicional",
            "reproche: deberías haber + participio",
            "reported speech en pasado",
        ],
    ),
    Theme(
        domain="viajar por trabajo vs. por placer",
        prompt=(
            "Conversad sobre la diferencia entre viajar por trabajo y "
            "viajar por placer: qué aporta cada uno, qué se pierde, qué "
            "prefiere el estudiante y por qué."
        ),
        target_structures=[
            "verbos de preferencia + infinitivo/que + subjuntivo",
            "lo + adjetivo + es",
            "comparativas enfáticas",
        ],
    ),
    Theme(
        domain="proyecto que lideraste",
        prompt=(
            "Pídele al estudiante que te hable de un proyecto que haya "
            "liderado: cómo lo organizó, qué problemas tuvo, qué haría "
            "distinto hoy."
        ),
        target_structures=[
            "pretérito perfecto de subjuntivo en valoraciones",
            "condicional compuesto",
            "conectores de orden",
        ],
    ),
    Theme(
        domain="costumbres de otra cultura",
        prompt=(
            "Pregúntale por costumbres de otra cultura que le sorprendieron "
            "positiva o negativamente. Pide comparaciones con las suyas."
        ),
        target_structures=[
            "me chocó que + imperfecto de subjuntivo",
            "en comparación con",
            "tanto como / más que / menos que",
        ],
    ),
    Theme(
        domain="cambios en tu ciudad",
        prompt=(
            "Conversa sobre cómo ha cambiado la ciudad del estudiante en "
            "los últimos años: qué ha mejorado, qué ha empeorado, qué le "
            "preocupa del futuro."
        ),
        target_structures=[
            "pretérito perfecto en balances",
            "hace + tiempo + que + presente",
            "ojalá + subjuntivo",
        ],
    ),
    Theme(
        domain="educación de hoy",
        prompt=(
            "Debate sobre cómo debería ser la educación actual. Pide al "
            "estudiante qué cambiaría si pudiera reformarla."
        ),
        target_structures=[
            "si + imperfecto de subjuntivo + condicional",
            "sería bueno que + subjuntivo",
            "en lugar de + infinitivo",
        ],
    ),
]


_C1_THEMES: list[Theme] = [
    Theme(
        domain="IA en la sociedad",
        prompt=(
            "Conversa con el estudiante sobre el papel creciente de la "
            "inteligencia artificial: oportunidades, riesgos, regulación. "
            "Pide matices y ejemplos actuales."
        ),
        target_structures=[
            "matizadores (en cierta medida, hasta cierto punto)",
            "subjuntivo en valoraciones de hipótesis",
            "estructuras nominales complejas",
        ],
    ),
    Theme(
        domain="crisis climática y acción individual",
        prompt=(
            "Debate hasta qué punto la acción individual importa frente a "
            "la sistémica. Pide al estudiante que defienda una postura con "
            "argumentos sólidos."
        ),
        target_structures=[
            "concesivas con por más que / por mucho que",
            "condicional de cortesía en argumentación",
            "léxico abstracto (sostenibilidad, transición)",
        ],
    ),
    Theme(
        domain="arte como protesta",
        prompt=(
            "Hablad del arte como vehículo de protesta: ejemplos que "
            "conozca el estudiante, límites éticos, impacto real."
        ),
        target_structures=[
            "voz pasiva perifrástica",
            "relativas con preposición + que / cual",
            "registro formal escrito/hablado",
        ],
    ),
    Theme(
        domain="futuro del trabajo humano",
        prompt=(
            "Conversad sobre qué trabajos desaparecerán y qué significará "
            "eso para el sentido del trabajo humano. Pide proyecciones "
            "argumentadas."
        ),
        target_structures=[
            "futuro perfecto",
            "no es que + subjuntivo, sino que + indicativo",
            "perífrasis verbales (llegar a, acabar por)",
        ],
    ),
    Theme(
        domain="tradiciones que deberían desaparecer",
        prompt=(
            "Pregúntale qué tradiciones cree que deberían desaparecer o "
            "transformarse, y por qué. Rebátele con contraargumentos."
        ),
        target_structures=[
            "subjuntivo en oraciones de relativo hipotéticas",
            "estructuras enfáticas (lo que / quien + subjuntivo)",
            "matización de opinión",
        ],
    ),
    Theme(
        domain="papel de los medios",
        prompt=(
            "Debate sobre la responsabilidad de los medios de comunicación "
            "en la polarización actual. Pide fuentes o ejemplos que el "
            "estudiante haya leído."
        ),
        target_structures=[
            "reported speech en registro formal",
            "conectores argumentativos (no obstante, por ende)",
            "verbos de opinión matizados",
        ],
    ),
    Theme(
        domain="dilema ético reciente",
        prompt=(
            "Preséntale un dilema ético (por ejemplo, datos médicos en "
            "seguros) y pídele que argumente su posición. Desafíale con "
            "un contraejemplo."
        ),
        target_structures=[
            "subjuntivo tras expresiones de duda/negación",
            "condicionales mixtos",
            "si bien + indicativo",
        ],
    ),
    Theme(
        domain="salud mental en la sociedad",
        prompt=(
            "Conversa sobre cómo ha cambiado el discurso público sobre "
            "salud mental. Pide opiniones sobre el impacto de redes "
            "sociales y de la destigmatización."
        ),
        target_structures=[
            "pretérito pluscuamperfecto de subjuntivo",
            "lo + adjetivo + es que",
            "sustantivación de adjetivos",
        ],
    ),
    Theme(
        domain="identidad cultural globalizada",
        prompt=(
            "Hablad de la tensión entre identidad local y cultura global. "
            "Pide al estudiante ejemplos propios: comida, música, idioma."
        ),
        target_structures=[
            "cuanto más / menos + subjuntivo",
            "se trata de + infinitivo / sustantivo",
            "léxico cultural específico",
        ],
    ),
    Theme(
        domain="libro o ensayo transformador",
        prompt=(
            "Que el estudiante te hable de un libro o ensayo que le cambió "
            "la forma de pensar: qué argumentaba, con qué estuvo o no de "
            "acuerdo, qué le queda hoy."
        ),
        target_structures=[
            "estilo indirecto con subjuntivo",
            "verbos argumentativos (sostener, plantear, refutar)",
            "conclusiones matizadas",
        ],
    ),
]


THEMES_BY_LEVEL: dict[CEFRBand, list[Theme]] = {
    "A1": _A1_THEMES,
    "A2": _A2_THEMES,
    "B1": _B1_THEMES,
    "B2": _B2_THEMES,
    "C1": _C1_THEMES,
}


def get_session_theme(
    *,
    level: CEFRBand,
    recent_domains: list[str],
    cooldown: int = 3,
) -> Theme:
    pool = THEMES_BY_LEVEL[level]
    recent = set(recent_domains[-cooldown:]) if cooldown > 0 else set()
    candidates = [t for t in pool if t.domain not in recent]
    if not candidates:
        return NEUTRAL_THEME
    return random.choice(candidates)
