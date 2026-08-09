"""B2 error-pattern vocabulary — the tracking key for progress over time.

Free-text `patron` prose is not stable run to run (spec 034 §Why: the same
transcript produced different pattern names *and* different `tipo` values
across two runs), so it cannot be matched on across sessions. `pattern_id` is
the stable key; `patron` stays as the human-readable label.

Granularity is the whole design problem, and the target is **the teachable
unit** — what a tutor would drill in one go. Too coarse
(`gramatica-preposiciones`) and every preposition fault collapses into one id,
hiding the change the progress report exists to show. Too fine
(`miedo-para-infinitivo`) and near-identical faults split across ids, so
recurrence reads as zero.

`tipo_habitual` is metadata, **not** part of the key. The same fault gets one
id whether a given run labels it `calco` or `gramatica` — that instability is
exactly what this vocabulary routes around, so ids describe the linguistic
fault rather than mirroring the `tipo` split.

Seeded from the stored `examiner.json` corpus (spec 034 OQ1), then hand-edited.
Entries marked "corpus" were observed in real sessions.
"""

from dataclasses import dataclass
from typing import Literal

# Error taxonomy. Shared with the examiner output schema, which re-exports it.
# "calco" is the priority category; loanwords are deliberately not a category
# (acceptance varies by region and register — see prompts/examiner_v*.md).
Tipo = Literal["calco", "gramatica", "lexico", "registro"]

# The tracking key. `otro` is the escape hatch: when nothing fits, `patron`
# carries the meaning and the finding is excluded from recurrence tracking.
PatternId = Literal[
    # Modo verbal — subjuntivo
    "subjuntivo-tras-deseo",
    "subjuntivo-tras-emocion-duda",
    "subjuntivo-tras-conector-final",
    "subjuntivo-tras-conector-condicional",
    "subjuntivo-tras-conector-temporal",
    "subjuntivo-tras-conector-concesivo",
    "subjuntivo-en-relativa-indefinida",
    "indicativo-tras-si-real",
    "condicional-irreal-presente",
    "condicional-irreal-pasado",
    # Tiempos y aspecto
    "preterito-vs-imperfecto",
    "perfecto-vs-indefinido",
    "pluscuamperfecto-uso",
    "futuro-vs-perifrasis",
    "gerundio-sobreusado",
    "infinitivo-vs-subjuntivo-mismo-sujeto",
    "conjugacion-irregular",
    # Concordancia
    "concordancia-genero",
    "concordancia-numero",
    "concordancia-sujeto-verbo",
    "genero-sustantivo-irregular",
    # Preposiciones y régimen
    "por-vs-para",
    "regimen-verbo-preposicion",
    "verbo-sin-preposicion",
    "preposicion-lugar",
    "a-personal",
    "preposicion-tiempo",
    # Pronombres
    "pronombre-objeto-directo-indirecto",
    "se-impersonal-vs-pasiva",
    "pronombre-sujeto-redundante",
    "verbos-tipo-gustar",
    # Ser / estar y estados
    "ser-vs-estar",
    "haber-vs-estar",
    "tener-vs-estar-expresiones",
    # Calcos estructurales del inglés
    "calco-hacer-sentido",
    "calco-aplicar-para",
    "calco-estoy-bueno",
    "calco-en-orden-de",
    "calco-la-razon-es-porque",
    "calco-seguir-con-gerundio",
    "calco-verbo-mas-preposicion-inglesa",
    "calco-estructura-enfatica",
    # Falsos amigos
    "falso-amigo-realizar",
    "falso-amigo-soportar-atender",
    "falso-amigo-eventualmente-actualmente",
    # Léxico
    "palabra-imprecisa",
    "confusion-pares-minimos",
    "coloquial-por-formal",
    # Discurso
    "muletillas-excesivas",
    "autocorreccion-excesiva",
    "conector-ausente-o-repetido",
    # Escape hatch — excluded from recurrence tracking
    "otro",
]


@dataclass(frozen=True)
class Patron:
    id: PatternId
    etiqueta: str  # short Spanish label, shown to the model and in notes
    tipo_habitual: Tipo  # the type this usually gets; NOT part of the key
    ejemplos: tuple[str, ...]  # concrete wrong forms, to anchor the choice


PATRONES: list[Patron] = [
    # ── Modo verbal — subjuntivo ────────────────────────────────────────────
    Patron(
        "subjuntivo-tras-deseo",
        "Subjuntivo tras expresión de deseo o voluntad",
        "gramatica",
        ("espero que puede venir", "quiero que vienes", "ojalá tengo tiempo"),
    ),
    Patron(
        "subjuntivo-tras-emocion-duda",
        "Subjuntivo tras emoción, duda o valoración",
        "gramatica",
        ("me alegra que estás aquí", "dudo que es verdad", "es raro que viene"),
    ),
    Patron(
        "subjuntivo-tras-conector-final",
        "Subjuntivo tras conector final (para que, a fin de que)",
        "gramatica",
        ("para que puedes entender", "a fin de que sabe"),
    ),
    Patron(
        "subjuntivo-tras-conector-condicional",
        "Subjuntivo tras conector condicional (a menos que, siempre que)",
        "gramatica",
        ("a menos que vienes", "con tal de que puedes", "siempre que tienes tiempo"),
    ),
    Patron(
        "subjuntivo-tras-conector-temporal",
        "Subjuntivo tras conector temporal con referencia futura",
        "gramatica",
        ("cuando llego mañana te aviso", "en cuanto termino salimos"),
    ),
    Patron(
        "subjuntivo-tras-conector-concesivo",
        "Subjuntivo tras concesivo hipotético (aunque)",
        "gramatica",
        ("aunque llueve mañana, iré",),
    ),
    Patron(
        "subjuntivo-en-relativa-indefinida",
        "Subjuntivo en relativa de antecedente indefinido",
        "gramatica",
        ("busco un piso que tiene balcón", "necesito alguien que sabe inglés"),
    ),
    Patron(
        "indicativo-tras-si-real",  # corpus
        "Indicativo (no subjuntivo) en condicional real con «si»",
        "gramatica",
        ("si pueda pasar tiempo con los nativos", "si tenga tiempo, voy"),
    ),
    Patron(
        "condicional-irreal-presente",
        "Condicional irreal de presente (si + imperfecto de subjuntivo)",
        "gramatica",
        ("si tendría tiempo, iría", "si soy tú, no lo haría"),
    ),
    Patron(
        "condicional-irreal-pasado",  # corpus, both runs
        "Condicional irreal de pasado (si hubiera + habría)",
        "gramatica",
        ("si había aprendido antes", "si había pedido ayuda, sería mejor"),
    ),
    # ── Tiempos y aspecto ───────────────────────────────────────────────────
    Patron(
        "preterito-vs-imperfecto",
        "Pretérito indefinido frente a imperfecto",
        "gramatica",
        ("ayer estaba en Madrid dos horas", "cuando fui joven vivía allí"),
    ),
    Patron(
        "perfecto-vs-indefinido",
        "Pretérito perfecto frente a indefinido",
        "gramatica",
        ("ayer he ido al cine", "esta mañana fui al médico (peninsular)"),
    ),
    Patron(
        "pluscuamperfecto-uso",
        "Pluscuamperfecto para anterioridad en el pasado",
        "gramatica",
        ("cuando llegué, ya salió",),
    ),
    Patron(
        "futuro-vs-perifrasis",
        "Futuro simple frente a «ir a» + infinitivo",
        "gramatica",
        ("mañana voy a poder ir, creo que lloverá seguro",),
    ),
    Patron(
        "gerundio-sobreusado",
        "Gerundio donde el español usa infinitivo o relativa",
        "calco",
        ("hablando español es difícil", "el hombre hablando es mi padre"),
    ),
    Patron(
        "infinitivo-vs-subjuntivo-mismo-sujeto",
        "Infinitivo con sujeto único frente a subjuntivo",
        "gramatica",
        ("quiero que yo vaya", "espero que yo pueda"),
    ),
    Patron(
        "conjugacion-irregular",  # corpus
        "Conjugación irregular incorrecta o forma inventada",
        "gramatica",
        ("voy a arraquencer", "sintare", "poní"),
    ),
    # ── Concordancia ────────────────────────────────────────────────────────
    Patron(
        "concordancia-genero",  # corpus, both runs
        "Concordancia de género (artículo/adjetivo con sustantivo)",
        "gramatica",
        ("esta frase no es correcto", "otro razón", "a razón"),
    ),
    Patron(
        "concordancia-numero",
        "Concordancia de número",
        "gramatica",
        ("las casa", "muchos persona"),
    ),
    Patron(
        "concordancia-sujeto-verbo",
        "Concordancia de sujeto y verbo",
        "gramatica",
        ("la gente son", "mis amigos viene"),
    ),
    Patron(
        "genero-sustantivo-irregular",
        "Género de sustantivos irregulares",
        "gramatica",
        ("la problema", "el mano", "la día"),
    ),
    # ── Preposiciones y régimen ─────────────────────────────────────────────
    Patron(
        "por-vs-para",
        "«por» frente a «para» (causa frente a finalidad)",
        "gramatica",
        ("lo hice por comprar pan", "gracias para tu ayuda"),
    ),
    Patron(
        "regimen-verbo-preposicion",  # corpus
        "Régimen preposicional del verbo (preposición equivocada)",
        "gramatica",
        ("me da miedo para salir", "soñar de", "depender en", "entrar a"),
    ),
    Patron(
        "verbo-sin-preposicion",  # corpus
        "Preposición añadida a un verbo que no la lleva",
        "gramatica",
        ("escuchar a español", "buscar por las llaves", "mirar a la tele"),
    ),
    Patron(
        "preposicion-lugar",
        "Preposición de lugar (en / a / de)",
        "gramatica",
        ("fui en casa", "estoy a la oficina"),
    ),
    Patron(
        "a-personal",
        "«a» personal ante complemento directo de persona",
        "gramatica",
        ("veo mi hermano", "conozco María"),
    ),
    Patron(
        "preposicion-tiempo",
        "Preposición temporal (en / por / durante / desde hace)",
        "gramatica",
        ("vivo aquí por tres años", "en la mañana (peninsular: por)"),
    ),
    # ── Pronombres ──────────────────────────────────────────────────────────
    Patron(
        "pronombre-objeto-directo-indirecto",
        "Pronombre de objeto directo frente a indirecto",
        "gramatica",
        ("le vi ayer", "lo di el libro"),
    ),
    Patron(
        "se-impersonal-vs-pasiva",
        "«se» impersonal frente a pasiva refleja",
        "gramatica",
        ("se vende casas", "aquí se habla inglés y francés (concordancia)"),
    ),
    Patron(
        "pronombre-sujeto-redundante",
        "Pronombre sujeto redundante (calco del inglés obligatorio)",
        "calco",
        ("yo creo que yo voy a ir porque yo tengo tiempo",),
    ),
    Patron(
        "verbos-tipo-gustar",
        "Verbos tipo «gustar» (sujeto y experimentante invertidos)",
        "gramatica",
        ("yo gusto el café", "me gusta los libros"),
    ),
    # ── Ser / estar y estados ───────────────────────────────────────────────
    Patron(
        "ser-vs-estar",
        "«ser» frente a «estar»",
        "gramatica",
        ("soy cansado", "la fiesta está en mi casa"),
    ),
    Patron(
        "haber-vs-estar",
        "«hay» frente a «está/están»",
        "gramatica",
        ("hay el libro en la mesa", "está un problema"),
    ),
    Patron(
        "tener-vs-estar-expresiones",
        "Expresiones con «tener» frente a «estar/ser»",
        "gramatica",
        ("estoy hambre", "soy 30 años", "estoy razón"),
    ),
    # ── Calcos estructurales del inglés ─────────────────────────────────────
    Patron(
        "calco-hacer-sentido",
        "«hacer sentido» por «tener sentido» (make sense)",
        "calco",
        ("eso no hace sentido", "no hace sentido para mí"),
    ),
    Patron(
        "calco-aplicar-para",
        "«aplicar para» por «solicitar» (apply for)",
        "calco",
        ("aplicar para un trabajo", "apliqué para la beca"),
    ),
    Patron(
        "calco-estoy-bueno",
        "«estoy bueno» por «estoy bien» (I'm good)",
        "calco",
        ("estoy bueno, gracias",),
    ),
    Patron(
        "calco-en-orden-de",
        "«en orden de» por «para» (in order to)",
        "calco",
        ("en orden de mejorar", "en orden a conseguirlo"),
    ),
    Patron(
        "calco-la-razon-es-porque",  # corpus
        "«la razón … es porque» (the reason is because)",
        "calco",
        ("la razón por esto es porque quiero practicar",),
    ),
    Patron(
        "calco-seguir-con-gerundio",  # corpus
        "«seguir con» + gerundio por «seguir» + gerundio (keep on doing)",
        "calco",
        ("seguir con hablando en español",),
    ),
    Patron(
        "calco-verbo-mas-preposicion-inglesa",  # corpus
        "Preposición inglesa arrastrada tras el verbo (afraid to, listen to)",
        "calco",
        ("me da miedo para pasar tiempo fuera", "escuchar a español"),
    ),
    Patron(
        "calco-estructura-enfatica",
        "Estructura enfática calcada (it's not to be…, what I mean is…)",
        "calco",
        ("no es para ser extraño", "lo que quiero decir es que"),
    ),
    # ── Falsos amigos ───────────────────────────────────────────────────────
    Patron(
        "falso-amigo-realizar",
        "«realizar» con el sentido inglés de «darse cuenta»",
        "calco",
        ("realicé que era tarde",),
    ),
    Patron(
        "falso-amigo-soportar-atender",
        "«soportar» por «apoyar», «atender» por «asistir a»",
        "calco",
        ("te soporto en tu decisión", "atendí la reunión"),
    ),
    Patron(
        "falso-amigo-eventualmente-actualmente",
        "«eventualmente» por «finalmente», «actualmente» por «en realidad»",
        "calco",
        ("eventualmente llegué", "actualmente no lo sabía"),
    ),
    # ── Léxico ──────────────────────────────────────────────────────────────
    Patron(
        "palabra-imprecisa",  # corpus
        "Palabra existente pero imprecisa para el sentido buscado",
        "lexico",
        ("mi género es… (por «lema» o «consejo»)",),
    ),
    Patron(
        "confusion-pares-minimos",  # corpus
        "Confusión entre pares parecidos (cuatro/cuarto, pero/perro)",
        "lexico",
        ("cuarto de los cinco días", "actual/actualmente"),
    ),
    Patron(
        "coloquial-por-formal",
        "Registro coloquial donde el contexto pide formal",
        "registro",
        ("vale, tío, en una exposición formal",),
    ),
    # ── Discurso ────────────────────────────────────────────────────────────
    Patron(
        "muletillas-excesivas",  # corpus
        "Muletillas excesivas que rompen el discurso",
        "registro",
        ("pues… este… o sea… bueno…",),
    ),
    Patron(
        "autocorreccion-excesiva",  # corpus
        "Autocorrecciones y reformulaciones constantes",
        "registro",
        ("mi confianos, mi confianos es…", "no tengo no tengo planes"),
    ),
    Patron(
        "conector-ausente-o-repetido",
        "Ausencia de conectores o repetición del mismo",
        "registro",
        ("y… y… y…", "yuxtaposición sin conector en argumentación"),
    ),
]

# Every id except the escape hatch, in declaration order. `otro` is excluded:
# it is a bucket, not a pattern, and must never enter recurrence tracking.
PATRON_IDS: tuple[PatternId, ...] = tuple(p.id for p in PATRONES)

PATRONES_POR_ID: dict[PatternId, Patron] = {p.id: p for p in PATRONES}
