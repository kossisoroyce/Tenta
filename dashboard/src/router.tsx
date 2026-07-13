import { useSyncExternalStore } from "react";

export const ROUTES = [
  "overview",
  "scoring",
  "storage",
  "drift",
  "models",
  "healing",
  "governance",
  "feedback",
  "benchmarks",
] as const;

export type Route = (typeof ROUTES)[number];

function subscribe(callback: () => void) {
  window.addEventListener("hashchange", callback);
  return () => window.removeEventListener("hashchange", callback);
}

function currentRoutePart(): string {
  return window.location.hash.replace(/^#\/?/, "").split(/[/?]/)[0];
}

function currentSearchPart(): string {
  const hash = window.location.hash.replace(/^#\/?/, "");
  const query = hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "";
  return query;
}

function getSnapshot(): Route {
  const raw = currentRoutePart();
  return (ROUTES as readonly string[]).includes(raw) ? (raw as Route) : "overview";
}

function getSearchSnapshot(): string {
  return currentSearchPart();
}

export function useRoute(): Route {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

export function useRouteParams(): URLSearchParams {
  return new URLSearchParams(useSyncExternalStore(subscribe, getSearchSnapshot, getSearchSnapshot));
}

export function navigate(route: Route, params?: Record<string, string | number | null | undefined>) {
  const query = new URLSearchParams();
  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "") query.set(key, String(value));
  });
  const suffix = query.toString() ? `?${query.toString()}` : "";
  window.location.hash = `#/${route}${suffix}`;
}
