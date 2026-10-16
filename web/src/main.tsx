import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import '@fontsource-variable/hanken-grotesk';
import './design/vayu.css';
import './design/graph.css';
import { applyTextSize, applyTheme, currentTextSize, currentTheme } from './lib/theme';

applyTheme(currentTheme());
applyTextSize(currentTextSize());

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
