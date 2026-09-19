import assert from 'node:assert/strict';
import test from 'node:test';
import { normalizeCityCamera3d } from '../src/lib/cityCamera3d.js';
import { parseObserverViewState, patchObserverViewState } from '../src/app/observerViewStateCore.js';
import { cityEvidenceParams, cityWorkspaceHref } from '../src/app/cityNavigation.js';

test('3D camera survives rendering modes and evidence bookmarks with its selected day', () => {
  const camera = '-45.125,100,110,0,0,0,2.6';
  const params = patchObserverViewState(new URLSearchParams('tick=4&agent=2&view=3d'), {camera3d:camera});
  const list = patchObserverViewState(params, {view:'list'});
  assert.equal(parseObserverViewState(list).camera3d, camera);
  const evidence = parseObserverViewState(cityEvidenceParams(parseObserverViewState(params)));
  const restored = new URL(cityWorkspaceHref('run-a', evidence), 'http://localhost');
  assert.equal(restored.searchParams.get('camera3d'), camera);
  assert.equal(restored.searchParams.get('tick'), '4');
  assert.equal(restored.searchParams.get('agent'), '2');
  assert.equal(restored.searchParams.get('view'), '3d');
});

test('3D camera rejects invalid numeric payloads and bounds its display coordinates', () => {
  for (const value of ['',null,'NaN,100,110,0,0,0,2','95,100,110,0,0,0,99',
    '95,100,110,0,0,0,.01','10001,100,110,0,0,0,2','0,0,0,0,0,0,2','<script>']) {
    assert.equal(normalizeCityCamera3d(value), null);
  }
  assert.equal(normalizeCityCamera3d('95.12349,100,110,-0.0004,0,0,2.6000'), '95.123,100,110,0,0,0,2.6');
});
