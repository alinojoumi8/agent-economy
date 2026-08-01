import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router";
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
  layer: string;
  q: string;
  activeOnly: boolean;
  agent: number | null;
};

export type ObserverViewPatch = Partial<{
  fork: string | null;
  tick: string | null;
  event: number | null;
  layer: string | null;
  q: string | null;
  activeOnly: boolean;
  agent: number | null;
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
  state: Pick<ObserverViewState, "fork" | "tick" | "event">,
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
  (patch: ObserverViewPatch, options?: { replace?: boolean }) => void,
] {
  const [params, setParams] = useSearchParams();
  const state = useMemo(() => parseObserverViewState(params), [params]);
  const patch = useCallback((
    update: ObserverViewPatch,
    options: { replace?: boolean } = {},
  ) => {
    setParams(patchObserverViewState(params, update), { replace: options.replace });
  }, [params, setParams]);
  return [state, patch];
}
