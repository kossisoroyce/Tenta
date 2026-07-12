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

function getSnapshot(): Route {
  const raw = window.location.hash.replace(/^#\/?/, "").split("/")[0];
  return (ROUTES as readonly string[]).includes(raw) ? (raw as Route) : "overview";
}

export function useRoute(): Route {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

export function navigate(route: Route) {
  window.location.hash = `#/${route}`;
}
