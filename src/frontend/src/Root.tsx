import { useEffect, useState } from "react";
import { App } from "./App";
import { Case1App } from "./Case1App";
import { Case2App } from "./Case2App";
import { parseAppRoute, type AppRoute } from "./api";

export function Root() {
  const [route, setRoute] = useState<AppRoute>(() => parseAppRoute());

  useEffect(() => {
    const onHash = () => setRoute(parseAppRoute());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  if (route === "case1") {
    return <Case1App />;
  }
  if (route === "case2") {
    return <Case2App />;
  }
  return <App />;
}
