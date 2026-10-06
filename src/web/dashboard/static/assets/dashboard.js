import { createEvents } from './js/events.js';
import { createRenderer } from './js/render.js';

const events = createEvents(() => render());
const render = createRenderer(events);

render();
events.loadSummary();
