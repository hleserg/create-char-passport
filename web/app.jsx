/* global React, ReactDOM, Stepper, LayerRail, PHASES */
const { useState: useStateApp } = React;

/* sample original characters for the demo (graphic-novel cast) */
const SAMPLE_CHARS = [
  { id: "geron", name: "Герон", status: "пайп не завершён", step: "passport" },
  { id: "tayra", name: "Тайра", status: "готов", step: null },
  { id: "lucius", name: "Луций", status: "только анкета", step: "data" },
];

/* example layer values shown in the rail for the active character */
const SAMPLE_LAYERS_VALUES = {
  style: "graphic novel, ink line + muted watercolour, dramatic lighting",
  face: "coarse face, broad nose, full lips, deep-set dark eyes, short rough dark hair, weathered tanned skin",
  body: "stocky, powerfully built, broad shoulders, faded tattoo on left forearm",
  outfit: "dark fur-trimmed leather tunic, wide belt",
  expression: "neutral",
  composition: "front portrait, head & shoulders, grey background",
};

/* compute layer status map for a given phase + passport substep */
function computeLayers(phase, pStep, frozen) {
  const L = { style: "idle", face: "idle", body: "idle", outfit: "idle", expression: "idle", composition: "idle" };
  L.style = frozen.style ? "frozen" : "active";
  if (phase === "data") {
    L.face = "idle"; L.body = "idle"; L.outfit = frozen.body ? "ro" : "idle";
    L.expression = "idle"; L.composition = "idle";
  } else if (phase === "passport") {
    if (pStep === 0) { L.face = "active"; L.body = "idle"; L.outfit = "active"; L.expression = "ro"; L.composition = "ro"; }
    else if (pStep === 1) { L.face = "frozen"; L.body = "active"; L.outfit = "active"; L.expression = "ro"; L.composition = "ro"; }
    else { L.face = "frozen"; L.body = "frozen"; L.outfit = "ro"; L.expression = "ro"; L.composition = "ro"; }
  } else if (phase === "emotions") {
    L.face = "frozen"; L.body = "frozen"; L.outfit = "ro"; L.expression = "active"; L.composition = "ro";
  } else if (phase === "outfit") {
    L.face = "frozen"; L.body = "frozen"; L.outfit = "active"; L.expression = "ro"; L.composition = "ro";
  } else if (phase === "props") {
    L.face = "ro"; L.body = "ro"; L.outfit = "idle"; L.expression = "idle"; L.composition = "active";
  } else if (phase === "dataset") {
    L.face = "frozen"; L.body = "frozen"; L.outfit = "ro"; L.expression = "ro"; L.composition = "active";
  }
  return L;
}

/* layer values to display (dim future layers) */
function layerValues(phase, pStep) {
  const v = { ...SAMPLE_LAYERS_VALUES };
  if (phase === "passport" && pStep === 0) { v.body = ""; }
  if (phase === "data") { v.face = ""; v.body = ""; v.expression = ""; v.composition = ""; }
  return v;
}

function App() {
  const [phase, setPhase] = useStateApp("start");
  const [done, setDone] = useStateApp([]);
  const [pStep, setPStep] = useStateApp(0);
  const [variant, setVariant] = useStateApp("A"); // passport layout variant
  const [activeChar, setActiveChar] = useStateApp("Герон");
  const [activeCharId, setActiveCharId] = useStateApp(null);
  const [cost, setCost] = useStateApp(0); // running session cost, USD
  const [lightbox, setLightbox] = useStateApp(null);
  window.__bumpCost = (n) => setCost((c) => c + n); // optimistic USD bump
  window.__setCost = (usd) => { if (typeof usd === "number" && !isNaN(usd)) setCost(usd); };
  window.__lightbox = (url) => setLightbox(url);

  // Load the real accumulated session cost (USD) from the backend on start.
  React.useEffect(() => {
    window.api.session().then((d) => d && d.cost && window.__setCost(d.cost.total_usd)).catch(() => {});
  }, []);

  const frozen = {
    style: phase !== "start",
    face: (phase === "passport" && pStep >= 1) || ["emotions", "outfit", "props", "dataset"].includes(phase),
    body: (phase === "passport" && pStep >= 2) || ["emotions", "outfit", "props", "dataset"].includes(phase),
  };

  function go(toPhase) {
    // mark previous phases done as we move forward
    const idx = PHASES.findIndex((p) => p.key === toPhase);
    const newDone = PHASES.slice(0, idx).map((p) => p.key);
    setDone(newDone);
    setPhase(toPhase);
    if (toPhase === "passport") setPStep(0);
    window.scrollTo({ top: 0 });
  }

  const ctx = { phase, setPhase, go, pStep, setPStep, variant, setVariant, activeChar, setActiveChar, activeCharId, setActiveCharId, done };

  const layers = computeLayers(phase, pStep, frozen);
  const values = layerValues(phase, pStep);

  const ScreenMap = {
    start: window.ScreenStart,
    data: window.ScreenData,
    passport: window.ScreenPassport,
    emotions: window.ScreenEmotions,
    outfit: window.ScreenOutfit,
    props: window.ScreenProps,
    dataset: window.ScreenDataset,
  };
  const Screen = ScreenMap[phase];

  const showRail = phase !== "start";

  return (
    <div className="app">
      <div className="topbar">
        <div className="logo">
          <div className="logo-mark">П</div>
          <div className="logo-txt">
            <b>Паспорт героя</b>
            <span>конструктор референсов для графического романа</span>
          </div>
        </div>
        <div className="spacer"></div>
        <div className="cost-tag" title="Оценка стоимости платных запросов к ИИ за эту сессию в долларах США (по прайсу моделей)">
          <span className="coin">$</span>
          <span>Сессия: <b>≈ ${cost.toFixed(2)}</b></span>
        </div>
        {phase !== "start" && (
          <div className="who">
            <span className="av">{activeChar[0]}</span>
            герой: <b style={{ color: "var(--paper)" }}>{activeChar}</b>
          </div>
        )}
      </div>

      <Stepper current={phase} done={done} onNav={(k) => {
        // allow navigating to any phase up to current+done for the demo
        go(k);
      }} />

      <div className="main">
        <div className="workspace" style={!showRail ? { gridColumn: "1 / -1", maxWidth: 1040 } : null}>
          {Screen ? <Screen ctx={ctx} /> : (
            <div className="panel"><div className="center muted" style={{ padding: 40 }}>Экран «{phase}» в разработке…</div></div>
          )}
        </div>
        {showRail && <LayerRail layers={layers} values={values} />}
      </div>
      <window.DebugLastPrompt />
      {lightbox && <window.Lightbox url={lightbox} onClose={() => setLightbox(null)} />}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
