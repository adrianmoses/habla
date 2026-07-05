import { createRoot } from 'react-dom/client';
import App from './App';
import './styles/tokens.css';
import './styles/globals.css';

// TODO: re-enable React.StrictMode once VoiceClient.connect is idempotent
// under double-mount. For now StrictMode would open two WS + mic streams
// on Session mount in dev.
const rootEl = document.getElementById('root');
if (!rootEl) throw new Error('#root not found');
createRoot(rootEl).render(<App />);
