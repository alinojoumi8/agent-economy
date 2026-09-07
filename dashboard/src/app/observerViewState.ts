import { useCallback, useMemo, useRef } from "react";
import { useLocation, useSearchParams } from "react-router";
import {
  commonObserverParamsFromState as commonObserverParamsFromStateCore,
  commonObserverSearchParams as commonObserverSearchParamsCore,
  parseObserverViewState as parseObserverViewStateCore,
  patchObserverViewState as patchObserverViewStateCore,
  projectionScopeParams as projectionScopeParamsCore,
} from "./observerViewStateCore.js";

export type ObserverViewState = {
  fork: string | null;
  tick: string;
  event: number | null;
  city: string | null;
  layer: string;
  q: string;
  activeOnly: boolean;
  agent: number | null;
  follow: number | null;
  firm: number | null;
  household: number | null;
  institution: string | null;
  camera: { x: number; y: number; zoom: number } | null;
  place: number | null;
  project: string | null;
  population: "core" | "all" | "clusters";
  view: "atlas" | "diorama" | "recorded";
};

export type ObserverViewPatch = Partial<{
  fork: string | null;
  tick: string | null;
  event: number | null;
  layer: string | null;
  q: string | null;
  activeOnly: boolean;
  agent: number | null;
  follow: number | null;
  firm: number | null;
  household: number | null;
  institution: string | null;
  camera: { x: number; y: number; zoom: number } | null;
  place: number | null;
  project: string | null;
  population: "core" | "all" | "clusters" | null;
  view: "atlas" | "diorama" | "recorded" | null;
}>;

export function parseObserverViewState(params: URLSearchParams): ObserverViewState {
  return parseObserverViewStateCore(params) as ObserverViewState;
}

export function patchObserverViewState(
  params: URLSearchParams,
  patch: ObserverViewPatch,
): URLSearchParams {
  return patchObserverViewStateCore(params, patch);
}

export function commonObserverSearchParams(params: URLSearchParams): URLSearchParams {
  return commonObserverSearchParamsCore(params);
}

export function commonObserverParamsFromState(
  state: Pick<ObserverViewState, "fork" | "tick" | "event"> & Partial<Pick<ObserverViewState, "city">>,
): URLSearchParams {
  return commonObserverParamsFromStateCore(state);
}

export function projectionScopeParams(
  state: Pick<ObserverViewState, "tick" | "fork">,
): URLSearchParams {
  return projectionScopeParamsCore(state);
}

export function useObserverViewState(): [
  ObserverViewState,
  (patch: ObserverViewPatch, options?: { replace?: boolean; onlyIfCurrent?: boolean }) => void,
] {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const pendingParams = useRef(params);
  const renderedLocation = useRef(location);
  const search = params.toString();
  if (renderedLocation.current !== location) {
    renderedLocation.current = location;
    pendingParams.current = params;
  }
  const state = useMemo(() => parseObserverViewState(params), [params]);
  const patch = useCallback((
    update: ObserverViewPatch,
    options: { replace?: boolean; onlyIfCurrent?: boolean } = {},
  ) => {
    // A completed request can trigger selection repair while a newer browser
    // navigation is still waiting for React to render. That older view must
    // not restore its URL. Interactive updates (including an ongoing drag)
    // continue to accumulate against the latest pending parameters.
    if (window.location.pathname !== location.pathname) return;
    if (options.onlyIfCurrent) {
      if (renderedLocation.current !== location) return;
      const browserSearch = new URLSearchParams(window.location.search).toString();
      if (browserSearch !== search || pendingParams.current.toString() !== search) return;
    }
    const next = patchObserverViewState(pendingParams.current, update);
    pendingParams.current = next;
    setParams(next, { replace: options.replace });
  }, [location, search, setParams]);
  return [state, patch];
}
