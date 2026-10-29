import { createRoadLayout } from './cityNavigation.js';

/** Renderer and walkers must use the same illustrative street geometry. */
export function planCityStreets(instances) {
  return createRoadLayout(instances).scenery;
}
