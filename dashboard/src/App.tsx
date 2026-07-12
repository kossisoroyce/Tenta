import { useCallback, useState, type ComponentType } from "react";

import { getOverview } from "./api";
import { useApi } from "./hooks";
import { Shell } from "./Shell";
import { useRoute, type Route } from "./router";

import { Overview } from "./views/Overview";
import { Scoring } from "./views/Scoring";
import { Storage } from "./views/Storage";
import { Models } from "./views/Models";
import { Drift } from "./views/Drift";
import { Healing } from "./views/Healing";
import { Governance } from "./views/Governance";
import { Feedback } from "./views/Feedback";
import { Benchmarks } from "./views/Benchmarks";

const VIEWS: Record<Route, ComponentType> = {
  overview: Overview,
  scoring: Scoring,
  storage: Storage,
  models: Models,
  drift: Drift,
  healing: Healing,
  governance: Governance,
  feedback: Feedback,
  benchmarks: Benchmarks,
};

export function App() {
  const route = useRoute();
  const { data: overview } = useApi(getOverview, 5000);
  const [mode, setMode] = useState<"light" | "dark">(() =>
    document.documentElement.dataset.mode === "dark" ? "dark" : "light",
  );

  const toggleTheme = useCallback(() => {
    setMode((current) => {
      const next = current === "dark" ? "light" : "dark";
      document.documentElement.dataset.mode = next;
      return next;
    });
  }, []);

  const View = VIEWS[route] ?? Overview;

  return (
    <Shell overview={overview} mode={mode} onToggleTheme={toggleTheme}>
      <View />
    </Shell>
  );
}
