/* global React, Panel, Help, Field, DoDont, PromptField, Preview, AIButton, Check, Toggle, Dialog, Figure, LAYER_DEFS */
const { useState: useS2 } = React;

/* =========================================================
   AI DIALOGS  (shared — exported to window)
   ========================================================= */
function AICheckDialog({ onClose, onAccept, layerName, reasoning, newPrompt }) {
  return (
    <Dialog onClose={onClose}>
      <h3>✦ ИИ проверил кадр</h3>
      <div className="panel soft" style={{ marginBottom: 14, background: "var(--blue-tint)", borderColor: "var(--blue)" }}>
        <div className="field-lbl"><span className="ru">Что говорит ИИ</span></div>
        <p style={{ margin: 0, color: "var(--ink)", fontSize: 14 }}>{reasoning}</p>
      </div>
      {newPrompt ? (
        <>
          <Field ru={"Предлагает поправить «" + layerName + "»"} en="">
            <PromptField value={newPrompt} readOnly rows={3} />
          </Field>
          <p className="muted" style={{ fontSize: 13 }}>Применить эту правку? Старый текст заменится на новый.</p>
          <div className="btnrow end">
            <button className="btn ghost" onClick={onClose}>Оставить как было</button>
            <button className="btn primary" onClick={() => { onAccept && onAccept(newPrompt); onClose(); }}>Принять правку</button>
          </div>
        </>
      ) : (
        <>
          <p className="muted">Замечаний нет — можно генерировать.</p>
          <div className="btnrow end"><button className="btn primary" onClick={onClose}>Понятно</button></div>
        </>
      )}
    </Dialog>
  );
}

function AIEditDialog({ onClose }) {
  const [stage, setStage] = useS2("ask");
  const [req, setReq] = useS2("");
  const results = [
    { step: "Лицо (FACE)", why: "Добавил «heavier brow» — так взгляд станет суровее, как вы просили.", prompt: "coarse face, broad nose, full lips, deep-set dark eyes, heavier brow, short rough dark hair, weathered tanned skin" },
    { step: "Тело (BODY)", why: "Усилил «broad scarred shoulders», чтобы образ читался более грозным.", prompt: "stocky, powerfully built, broad scarred shoulders, faded tattoo on left forearm" },
  ];
  return (
    <Dialog onClose={onClose} wide>
      <h3>✦ Правка с ИИ</h3>
      {stage === "ask" ? (
        <>
          <p>Опишите простыми словами, чего хотите добиться — ИИ просмотрит весь паспорт героя и
            предложит правки сразу по нужным шагам. Например: «сделай его более грозным и старше».</p>
          <Field ru="Чего хотите добиться?">
            <textarea className="in" rows={3} value={req} onChange={(e) => setReq(e.target.value)} placeholder="Хочу, чтобы Герон выглядел суровее и опаснее…" />
          </Field>
          <div className="btnrow end">
            <button className="btn ghost" onClick={onClose}>Отмена</button>
            <AIButton onClick={() => setStage("res")}>Отправить запрос</AIButton>
          </div>
        </>
      ) : (
        <>
          <p>ИИ предлагает правки по {results.length} шагам. Примите те, что нравятся — отмеченные шаги
            попросят перегенерировать кадр.</p>
          {results.map((r, i) => (
            <div className="panel soft" key={i} style={{ marginBottom: 12 }}>
              <div className="field-lbl"><span className="ru">{r.step}</span></div>
              <p style={{ fontSize: 13, color: "var(--ink-2)", margin: "0 0 8px" }}>{r.why}</p>
              <PromptField value={r.prompt} readOnly rows={2} />
              <div className="btnrow end" style={{ marginTop: 10 }}><button className="btn approve sm">Принять</button></div>
            </div>
          ))}
          <div className="btnrow end"><button className="btn ghost" onClick={onClose}>Закрыть</button></div>
        </>
      )}
    </Dialog>
  );
}

window.AICheckDialog = AICheckDialog;
window.AIEditDialog = AIEditDialog;

/* =========================================================
   PASSPORT — 5 frames, 3 layout variants
   ========================================================= */
const FRAMES = [
  { key: "face", n: 1, title: "Фас-портрет", fig: "front-portrait", cranks: "face",
    crit: "Лицо смотрит прямо в камеру, видно голову и плечи. Спокойное лицо, ровный серый фон, мягкий свет, без рамок и подписей.",
    why: "Это главный кадр — эталон лица. По нему нейросеть будет «узнавать» героя на всех остальных картинках. Здесь мы крутим и замораживаем ЛИЦО." },
  { key: "body", n: 2, title: "Фас, полный рост", fig: "front-full", cranks: "body",
    crit: "Видно героя ЦЕЛИКОМ — от макушки до обуви, без обрезки. Стоит прямо, стопы на земле, руки расслаблены, серый фон.",
    why: "Эталон телосложения. Лицо уже держится первым кадром, а здесь мы крутим и замораживаем ТЕЛО и базовый наряд." },
  { key: "profile", n: 3, title: "Профиль-портрет", fig: "profile-portrait", cranks: null,
    crit: "СТРОГИЙ профиль, 90° вбок — самый капризный кадр, тут нейросеть постоянно халтурит. Голова повёрнута ровно вбок, герой смотрит ПРЯМО ПЕРЕД СОБОЙ, а НЕ в камеру. Видна только ОДНА сторона лица: один глаз, одна бровь, одно ухо; нос и подбородок — чётким силуэтом на фоне. Это НЕ полуоборот и НЕ 3/4. Если лицо хоть немного развернулось к камере — перегенерируйте, нейросеть любит «подсматривать».",
    why: "Профиль нейросеть сама нарисовать не может — нужен эталон формы носа и подбородка сбоку. И она упорно норовит развернуть лицо обратно в 3/4 или к камере, поэтому тут придётся последить и, возможно, перегенерить пару раз." },
  { key: "back", n: 4, title: "Спина, полный рост", fig: "back-full", cranks: null,
    crit: "Вид со спины, в полный рост без обрезки. Видно затылок, причёску сзади, спину и одежду со спины.",
    why: "Затылок и спину нельзя «додумать» из вида спереди — поэтому снимаем отдельно." },
  { key: "3q", n: 5, title: "3/4, полный рост", fig: "threeq-full", cranks: null,
    crit: "Полуоборот примерно на 45°, в полный рост без обрезки, стопы на земле, серый фон.",
    why: "Объём фигуры на повороте — последний эталон для покрытия всех ракурсов." },
];

/* canonical COMPOSITION text per passport frame (advanced; edit only to nudge pose/camera) */
const FRAME_COMP = {
  face: "Front facing portrait, head and shoulders, plain neutral grey background, soft even lighting, neutral expression, no text, no panel border, no frame.",
  body: "Full-length character reference, head-to-toe, standing straight, both feet flat on the ground, legs and footwear visible, plain neutral grey background, soft even lighting, neutral expression, arms relaxed at sides, no frame.",
  profile: "Strict side profile, head facing 90 degrees to the side, only one eye visible, nose and lips in silhouette, head and shoulders, plain neutral grey background, soft even lighting, no frame.",
  back: "Full-length character reference seen from behind, back view, head-to-toe, back of the head, hairstyle and clothing from behind clearly visible, both feet flat on the ground, plain neutral grey background, no frame.",
  "3q": "Full-length character reference at a three-quarter angle, body turned about 45 degrees, head-to-toe, both feet flat on the ground, plain neutral grey background, soft even lighting, neutral expression, no frame.",
};

const VARIANTS = [
  ["A", "Форма → превью"],
  ["B", "Два столбца"],
  ["C", "Кадр крупно"],
];

function VariantSwitcher({ ctx }) {
  return (
    <div className="panel soft" style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 14px", marginBottom: 18, borderStyle: "dashed", borderColor: "var(--blue)", background: "var(--blue-tint)" }}>
      <span style={{ fontSize: 12.5, fontWeight: 700, color: "var(--blue-deep)" }}>🧪 Раскладка шага (на выбор):</span>
      <div className="btnrow" style={{ gap: 6 }}>
        {VARIANTS.map(([k, lbl]) => (
          <button key={k} className={"btn sm" + (ctx.variant === k ? " primary" : " ghost")} onClick={() => ctx.setVariant(k)}>{k} · {lbl}</button>
        ))}
      </div>
    </div>
  );
}

/* layer field block for a passport frame */
function PassportFields({ frame, step }) {
  const faceRO = step >= 1;
  const bodyRO = step >= 2;
  const showBody = step >= 1;
  const outfitRO = step >= 2;
  const [check, setCheck] = useS2(null);
  return (
    <>
      <Field ru="Лицо" en="FACE"
        right={faceRO ? <span className="badge lock">🔒 заморожено</span> : <span className="badge ro">собрано из анкеты</span>}
        hint={!faceRO ? <DoDont yes="форма лица, нос, губы, глаза, волосы, кожа, шрамы" no="выражение/эмоцию (это слой «Эмоция»), позу и фон, одежду" /> : null}>
        <PromptField readOnly={faceRO} rows={2} layer="Лицо" value="coarse face, broad nose, full lips, deep-set dark eyes, short rough dark hair, weathered tanned skin" />
      </Field>

      {showBody && (
        <Field ru="Тело" en="BODY"
          right={bodyRO ? <span className="badge lock">🔒 заморожено</span> : <span className="badge ro">собрано из анкеты</span>}
          hint={!bodyRO ? <DoDont yes="телосложение, рост (словами: «коренастый»), приметы на теле" no="одежду, лицо, позу или настроение" /> : null}>
          <PromptField readOnly={bodyRO} rows={2} layer="Тело" value="stocky, powerfully built, broad shoulders, faded tattoo on left forearm" />
        </Field>
      )}

      <Field ru="Одежда" en="OUTFIT"
        right={outfitRO ? <span className="badge ro">по базовому наряду</span> : <span className="badge now">базовый наряд — вводим тут</span>}
        hint={!outfitRO ? <DoDont yes="одежду, материал, крой, цвет наряда" no="телосложение, лицо, позу/фон, эмоцию" /> : null}>
        <PromptField readOnly={outfitRO} rows={1} layer="Одежда" value="dark fur-trimmed leather tunic, wide leather belt" />
      </Field>

      {/* Одна общая проверка: разом проверяет все заполняемые поля этого кадра */}
      {(!faceRO || !bodyRO || !outfitRO) && (
        <div className="btnrow" style={{ marginTop: 14 }}>
          <AIButton onClick={() => setCheck(
            step === 0
              ? { layer: "Лицо", reasoning: "Проверил «Лицо» и «Одежда» вместе. В описании лица затесалось слово «calm» — это выражение, ему место в слое «Эмоция». Предлагаю убрать. Одежда описана корректно — замечаний нет.", newPrompt: "coarse face, broad nose, full lips, deep-set dark eyes, short rough dark hair, weathered tanned skin" }
              : { layer: "поля кадра", reasoning: "Проверил «Тело» и «Одежда» вместе. Каждое поле описывает только своё (телосложение и наряд), слои не путаются — замечаний нет.", newPrompt: "" }
          )}>Проверить поля с ИИ</AIButton>
          <span className="muted" style={{ fontSize: 12 }}>проверит лицо{showBody ? ", тело" : ""} и одежду разом</span>
        </div>
      )}

      {check && <AICheckDialog onClose={() => setCheck(null)} layerName={check.layer} reasoning={check.reasoning} newPrompt={check.newPrompt} />}
    </>
  );
}

function PassportActions({ ctx, step, onEdit }) {
  const isLast = step >= FRAMES.length - 1;
  return (
    <div className="btnrow split">
      <button className="btn ghost" onClick={() => step > 0 ? ctx.setPStep(step - 1) : ctx.go("data")}>← Назад</button>
      <div className="btnrow">
        <AIButton onClick={onEdit}>Правка с ИИ</AIButton>
        <button className="btn approve" onClick={() => {
          if (isLast) ctx.go("emotions");
          else ctx.setPStep(step + 1);
          window.scrollTo({ top: 0 });
        }}>{isLast ? "Готово, дальше →" : "Утвердить кадр →"}</button>
      </div>
    </div>
  );
}

function ScreenPassport({ ctx }) {
  const step = ctx.pStep;
  const frame = FRAMES[step];
  const [gen, setGen] = useS2("ready"); // empty | gen | ready
  const [edit, setEdit] = useS2(false);

  function doGen() {
    if (window.__bumpCost) window.__bumpCost(8);
    // record exact prompt sent for the debug viewer
    const FACE = "coarse face, broad nose, full lips, deep-set dark eyes, short rough dark hair, weathered tanned skin";
    const BODY = "stocky, powerfully built, broad shoulders, faded tattoo on left forearm";
    const layers = { style: "graphic novel, bold ink linework, muted watercolour wash, dramatic chiaroscuro lighting" };
    if (["face", "profile", "3q"].includes(frame.key) || step >= 0) layers.face = FACE;
    if (step >= 1 || ["body", "back", "3q"].includes(frame.key)) layers.body = BODY;
    if (["face", "body"].includes(frame.key)) layers.outfit = "dark fur-trimmed leather tunic, wide leather belt";
    layers.composition = FRAME_COMP[frame.key];
    let refs;
    if (frame.key === "face") {
      // первый портрет: три стиль-рефа, лица/тела ещё нет
      refs = [
        { label: "стиль-реф 1", kind: "item", take: "use STYLE only — drawing manner, do not copy any character" },
        { label: "стиль-реф 2", kind: "item", take: "use STYLE only — drawing manner, do not copy any character" },
        { label: "стиль-реф 3", kind: "item", take: "use STYLE only — drawing manner, do not copy any character" },
      ];
    } else {
      refs = [{ label: "стиль-реф", kind: "item" }];
      refs.push({ label: "паспорт: фас-портрет (FACE)", kind: "front-portrait" });
      if (["profile", "back", "3q"].includes(frame.key)) refs.push({ label: "паспорт: фас, рост (BODY)", kind: "front-full" });
    }
    if (window.setLastGen) window.setLastGen({ section: "Паспорт", view: frame.title, layers,
      refs, model: "nano-banana", size: "1024×1536" });
    setGen("gen"); setTimeout(() => setGen("ready"), 1100);
  }

  // reset preview state when step changes is omitted for demo simplicity

  const previewBlock = (
    <Panel className={ctx.variant === "C" ? "" : "soft"} marks={ctx.variant === "C"}>
      <div className="pv-title">Кадр {frame.n} · {frame.title}</div>
      <div className={"pv " + (gen === "ready" ? "ready" : gen === "gen" ? "gen" : "empty")} style={{ minHeight: ctx.variant === "C" ? 360 : 230 }}>
        {gen === "gen" ? (<><div className="pv-spin"></div><span className="pv-cap">генерация…</span></>)
          : gen === "ready" ? (<><span className="pv-badge"><span className="badge done">✓ кадр готов</span></span><Figure kind={frame.fig} size={ctx.variant === "C" ? 130 : 92} /><span className="pv-cap">{frame.title}</span><span className="pv-sub">нейтральное лицо · серый фон</span></>)
            : (<><Figure kind={frame.fig} size={92} /><span className="pv-cap">нажмите «Сгенерировать»</span></>)}
      </div>
      <div className="btnrow" style={{ marginTop: 12 }}>
        <button className="btn primary" onClick={doGen}>{gen === "ready" ? "↻ Перегенерировать" : "Сгенерировать кадр"}</button>
        <AIButton onClick={() => {}}>Проверить кадр с ИИ</AIButton>
      </div>
      {gen === "ready" && <p className="muted" style={{ fontSize: 12, marginTop: 10, marginBottom: 0 }}>Не нравится — жмите «Перегенерировать». Прошлый вариант не пропадёт: он уйдёт в архив «отклонённые».</p>}
    </Panel>
  );

  const fieldsBlock = (
    <Panel key={"fields-" + frame.key} title="Описание кадра" icon="✍️" marks={ctx.variant !== "B"}
      collapsible={step >= 2} defaultCollapsed={step >= 2}
      badge={step >= 2 ? <span className="badge lock">🔒 всё заморожено</span> : null}>
      <PassportFields frame={frame} step={step} />
    </Panel>
  );

  const sceneBlock = (
    <AdvancedScene key={"scene-" + frame.key} value={FRAME_COMP[frame.key]}
      note={<>Это поле уже настроено под этот паспортный кадр. Меняйте его <b>только</b> чтобы поправить <b>положение героя</b> и <b>ракурс камеры</b> ближе к нужному виду (например, если герой смотрит не туда). Фон, свет и пометки «без рамок» лучше не трогать.</>} />
  );

  return (
    <div>
      <div className="eyebrow">Шаг 2 из 6 · Паспорт · кадр {frame.n} из 5</div>
      <h1 className="pagetitle">{frame.title}</h1>

      {/* substep chips */}
      <div className="btnrow" style={{ marginBottom: 18, gap: 7 }}>
        {FRAMES.map((f, i) => (
          <button key={f.key} className={"btn sm " + (i === step ? "primary" : i < step ? "approve" : "ghost")} onClick={() => ctx.setPStep(i)} style={{ minHeight: 32 }}>
            {i < step ? "✓ " : ""}{f.n}. {f.title}
          </button>
        ))}
      </div>

      <VariantSwitcher ctx={ctx} />

      <div className="notice">
        <span className="ic">⚠️</span>
        <span className="tx"><b>Это базовый кадр идентичности.</b> Важно, чтобы он точно соответствовал критерию ниже — от этих кадров зависит весь дальнейший набор. <br /><b>Критерий кадра:</b> {frame.crit}</span>
      </div>

      <Help title={"Что мы делаем на этом шаге?"}>
        <p>{frame.why}</p>
        <p>Заполните текстовые поля (или нажмите <b>✦ помощь ИИ</b>, чтобы их написала нейросеть),
          затем нажмите <b>«Сгенерировать кадр»</b>. Если кадр хороший — <b>«Утвердить»</b>.
          После утверждения слой замораживается 🔒 и дальше не меняется.</p>
        {step <= 1 && (
          <p><b>Про одежду.</b> Базовый наряд на этом шаге тоже можно менять. Но нейросеть не помнит
            одежду между кадрами, поэтому за согласованностью следите сами: наряд на <b>портрете</b> (кадр 1)
            и в <b>полный рост</b> (кадр 2) должен совпадать. Если одежда разъехалась — вернитесь к кадру 1,
            поправьте описание одежды, <b>перегенерируйте портрет</b>, а затем с <b>тем же</b> описанием
            генерируйте полный рост.</p>
        )}
      </Help>

      {/* layout variants */}
      {ctx.variant === "A" && (<>{fieldsBlock}{sceneBlock}{previewBlock}</>)}
      {ctx.variant === "B" && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 0.9fr", gap: 18, alignItems: "start" }}>
            <div>{fieldsBlock}</div>
            <div style={{ position: "sticky", top: 16 }}>{previewBlock}</div>
          </div>
          {sceneBlock}
        </>
      )}
      {ctx.variant === "C" && (<>{previewBlock}{sceneBlock}{fieldsBlock}</>)}

      <div style={{ marginTop: 22 }}>
        <PassportActions ctx={ctx} step={step} onEdit={() => setEdit(true)} />
      </div>

      {edit && <AIEditDialog onClose={() => setEdit(false)} />}
    </div>
  );
}

/* =========================================================
   EMOTIONS SCREEN
   ========================================================= */
const EMO_ROW = [
  { v: "neutral", ru: "спокойствие", fig: "front-portrait" },
  { v: "angry, furious", ru: "злость, ярость", fig: "front-portrait" },
  { v: "smiling warmly", ru: "тёплая улыбка", fig: "front-portrait" },
];

function EmotionCell({ e, onArchive }) {
  const [st, setSt] = useS2(e.v === "neutral" ? "ready" : "empty");
  function gen() { if (window.__bumpCost) window.__bumpCost(8);
    if (window.setLastGen) window.setLastGen({ section: "Эмоции", view: e.v + " (" + e.ru + ")",
      layers: {
        style: "graphic novel, bold ink linework, muted watercolour wash, dramatic chiaroscuro lighting",
        face: "coarse face, broad nose, full lips, deep-set dark eyes, short rough dark hair, weathered tanned skin",
        expression: e.v,
        composition: "front facing portrait, head and shoulders, plain neutral grey background, soft even lighting" },
      refs: [{ label: "стиль-реф", kind: "item" }, { label: "паспорт: фас-портрет (FACE)", kind: "front-portrait" }],
      model: "nano-banana", size: "1024×1024" });
    setSt("gen"); setTimeout(() => setSt("ready"), 1000); }
  function archive() { onArchive && onArchive(e.v); setSt("empty"); }
  return (
    <div className="pv-col">
      <div className="pv-title">{e.v}<br /><span style={{ fontWeight: 400, textTransform: "none", color: "var(--ink-2)", fontSize: 11 }}>{e.ru}</span></div>
      <div className={"pv " + (st === "ready" ? "ready" : st === "gen" ? "gen" : "empty")} style={{ minHeight: 150 }}>
        {st === "gen" ? (<><div className="pv-spin"></div><span className="pv-cap">генерация…</span></>)
          : st === "ready" ? (<><span className="pv-badge"><span className="badge done">✓</span></span><Figure kind={e.fig} size={58} /></>)
            : (<><Figure kind={e.fig} size={58} /><span className="pv-sub">нет кадра</span></>)}
      </div>
      {st === "ready" ? (
        <div className="btnrow" style={{ flexWrap: "nowrap", gap: 6 }}>
          <button className="btn warn sm" onClick={archive} title="Отправить этот кадр в архив (rejected)" style={{ flex: "0 0 auto" }}>🗑 Удалить</button>
          <button className="btn sm" onClick={gen} style={{ flex: 1 }}>↻ Заново</button>
        </div>
      ) : (
        <button className="btn sm" onClick={gen} style={{ width: "100%" }}>Сгенерировать</button>
      )}
    </div>
  );
}

function ScreenEmotions({ ctx }) {
  const [baseOn, setBaseOn] = useS2(true);
  const [baseSt, setBaseSt] = useS2("empty");
  const [archived, setArchived] = useS2(0);
  function genBase() { if (window.__bumpCost) window.__bumpCost(8); setBaseSt("gen"); setTimeout(() => setBaseSt("ready"), 1000); }
  return (
    <div>
      <div className="eyebrow">Шаг 3 из 6 · Эмоции · по желанию</div>
      <h1 className="pagetitle">Эмоции <span className="accent">{ctx.activeChar}</span></h1>
      <p className="kicker">Соберём эталоны мимики. Каждый кадр — крупный портрет: лицо одно и то же (его держит паспорт), меняется только выражение.</p>

      <Help title="Зачем отдельные кадры эмоций?">
        <p>Сильные эмоции (крик, широкая улыбка) нейросеть часто рисует плохо и «уводит» лицо.
          Поэтому делаем чистые эталоны злости и улыбки заранее — потом по ним легко добавлять эмоции в сценах.</p>
        <p>Это <b>необязательно</b>. Можно сгенерировать не все — кнопка «Готово» пропустит дальше даже с пустыми ячейками.</p>
      </Help>

      <Panel title="Три базовые эмоции" icon="🎭">
        <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>Под каждой — своя кнопка. Перегенерируется только та эмоция, под которой нажали.</p>
        <div className="pv-grid" style={{ gridTemplateColumns: "repeat(3,1fr)" }}>
          {EMO_ROW.map((e) => <EmotionCell key={e.v} e={e} onArchive={() => setArchived((n) => n + 1)} />)}
        </div>
        {archived > 0 && <p className="muted" style={{ fontSize: 12, marginTop: 12, marginBottom: 0 }}>🗑 Отправлено в архив за эту сессию: <b>{archived}</b> — лежат в папке <span className="mono">rejected/</span>.</p>}
      </Panel>

      <AdvancedScene value="Front facing portrait, head and shoulders, plain neutral grey background, soft even lighting." note={<>Кадры эмоций — крупный <b>портрет</b> (голова и плечи), одна и та же сцена на все три. Меняйте это поле <b>только</b> чтобы поправить план или ракурс (например, если лицо слишком мелкое). Фон и свет лучше не трогать.</>} />

      <Panel title="Эмоция по умолчанию" icon="🎯" badge={<span className="badge opt">по желанию</span>} actions={<Toggle on={baseOn} onToggle={setBaseOn} />}>
        <div style={{ opacity: baseOn ? 1 : 0.45, pointerEvents: baseOn ? "auto" : "none" }}>
          <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>«Обычное» выражение героя — будет подставляться во всех сценах вместо нейтрального.</p>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 170px", gap: 16, alignItems: "start" }}>
            <Field ru="Настроение героя" en="EXPRESSION" hint={<DoDont yes="короткое выражение по-английски: grim, smiling, furious" no="описание мимики прозой, позу, одежду или фон" />}>
              <PromptField value="grim, brooding" rows={1} layer="Эмоция" />
              <div className="btnrow" style={{ marginTop: 10 }}>
                <button className="btn sm" onClick={genBase}>{baseSt === "ready" ? "↻ Заново" : "Сгенерировать"}</button>
                <AIButton small onClick={() => {}}>Проверить</AIButton>
              </div>
            </Field>
            <div className="pv-col">
              <div className="pv-title">превью</div>
              <div className={"pv " + (baseSt === "ready" ? "ready" : baseSt === "gen" ? "gen" : "empty")} style={{ minHeight: 130 }}>
                {baseSt === "gen" ? <div className="pv-spin"></div> : baseSt === "ready" ? <Figure kind="front-portrait" size={54} /> : <Figure kind="front-portrait" size={54} />}
              </div>
            </div>
          </div>
        </div>
      </Panel>

      <div className="btnrow split" style={{ marginTop: 22 }}>
        <button className="btn ghost" onClick={() => ctx.go("passport")}>← Назад</button>
        <button className="btn go" onClick={() => ctx.go("outfit")}>Готово, дальше: наряды →</button>
      </div>
    </div>
  );
}

window.ScreenPassport = ScreenPassport;
window.ScreenEmotions = ScreenEmotions;
