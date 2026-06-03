/* global React, Panel, Help, Field, DoDont, PromptField, Preview, AIButton, Check, Toggle, Dialog, Figure, AdvancedScene, SceneModal */
const { useState: useS3 } = React;

/* =========================================================
   SCENE CARD — preview + own generate + edit-scene + approve
   ========================================================= */
function SceneCard({ frame, onStateChange, onArchive }) {
  const [st, setSt] = useS3(frame.initial || "empty");
  const [scene, setScene] = useS3(frame.scene);
  const [modal, setModal] = useS3(false);

  function setState(next) {setSt(next);onStateChange && onStateChange(frame.key, next);}
  function gen() {if (window.__bumpCost) window.__bumpCost(8);
    if (window.setLastGen) window.setLastGen({ section: frame.section || "Наряд", view: frame.title,
      layers: {
        style: "graphic novel, bold ink linework, muted watercolour wash, dramatic chiaroscuro lighting",
        face: "coarse face, broad nose, full lips, deep-set dark eyes, short rough dark hair, weathered tanned skin",
        body: "stocky, powerfully built, broad shoulders, faded tattoo on left forearm",
        outfit: frame.outfitPrompt || "ornate ceremonial plate armor, engraved pauldrons, crimson cloak",
        composition: scene },
      refs: [{ label: "стиль-реф", kind: "item" }, { label: "паспорт: фас-портрет (FACE)", kind: "front-portrait" }, { label: "паспорт: фас, рост (BODY)", kind: "front-full" }],
      model: "nano-banana", size: "1024×1536" });
    setState("gen");setTimeout(() => setState("ready"), 1000);}
  function archive() {onArchive && onArchive(frame.title);setState("empty");}

  // allow parent to trigger generation of missing frames
  React.useEffect(() => {
    frame._gen = gen;
    frame._state = st;
  });

  return (
    <div className="pv-col">
      <div className="pv-title">{frame.title}{frame.req && <span style={{ color: "var(--red)" }}> *</span>}</div>
      <div className={"pv " + (st === "ready" ? "ready" : st === "gen" ? "gen" : "empty")} style={{ minHeight: 160 }}>
        {st === "gen" ? <div className="pv-spin"></div> :
        st === "ready" ? <><span className="pv-badge"><span className="badge done">✓</span></span><Figure kind={frame.fig} size={62} /></> :
        <><Figure kind={frame.fig} size={62} /><span className="pv-sub" style={{ color: frame.req ? "var(--red)" : "var(--ink-3)" }}>{frame.req ? "нужен этот кадр" : "нет кадра"}</span></>}
      </div>
      {st === "ready" ?
      <div className="btnrow" style={{ flexWrap: "nowrap", gap: 6 }}>
          <button className="btn warn sm" onClick={archive} title="Отправить этот кадр в архив (rejected)" style={{ flex: "0 0 auto" }}>🗑 Удалить</button>
          <button className="btn sm" onClick={gen} style={{ flex: 1 }}>↻ Перегенерировать</button>
        </div> :

      <button className="btn sm" onClick={gen} style={{ width: "100%" }}>Сгенерировать</button>
      }
      <button className="btn ghost sm" onClick={() => setModal(true)} style={{ width: "100%" }}>⚙ Изменить сцену</button>
      {modal && <SceneModal title={frame.title} value={scene} onClose={() => setModal(false)}
      onApply={(txt, changed) => {setScene(txt);if (changed) gen();}} />}
    </div>);

}

function ScreenOutfit({ ctx }) {
  // multiple outfits for this character (from the анкета). Base is read-only here.
  const OUTFITS = [
    { id: "base", name: "Базовый костюм", prompt: "dark fur-trimmed leather tunic, wide leather belt", base: true, done: true },
    { id: "parade", name: "Парадный доспех", prompt: "ornate ceremonial plate armor, engraved pauldrons, crimson cloak", complex: true, done: false },
    { id: "travel", name: "Дорожный плащ", prompt: "worn travelling cloak, hood, leather satchel", complex: false, done: false },
  ];
  const [activeOutfit, setActiveOutfit] = useS3("parade");
  const outfit = OUTFITS.find((o) => o.id === activeOutfit) || OUTFITS[1];

  const [complex, setComplex] = useS3(true);
  const [details, setDetails] = useS3([{ id: 1, prompt: "close-up of engraved pauldron", st: "empty" }]);
  // per-frame generated state, lifted so we can gate "next"
  const [states, setStates] = useS3({ front: "ready", back: "empty", profile: "empty" });
  const [archived, setArchived] = useS3(0);

  function onCardState(key, next) {setStates((s) => ({ ...s, [key]: next }));}
  function archiveFrame() {setArchived((n) => n + 1);}

  return (
    <div>
      <div className="eyebrow">Шаг 4 из 6 · Наряды · по желанию</div>
      <h1 className="pagetitle">Наряды героя <span className="accent">{ctx.activeChar}</span></h1>
      <p className="kicker">У героя может быть несколько костюмов — выберите наряд вкладкой ниже и снимите его с нужных сторон. Лицо и тело уже заморожены, меняется только одежда.</p>

      <Help title="Что это за вкладки нарядов?">
        <p>Наряды вы перечислили в анкете героя. Здесь каждый <b>собирается отдельно</b> — переключайтесь
          вкладками. <b>Базовый костюм</b> уже снят на шаге паспорта, поэтому он только для справки (🔒).</p>
        <p>Для каждого наряда нужны минимум <b>Фас</b> и <b>Спина</b> <span style={{ color: "var(--red)" }}>*</span>.
          Не нравится кадр — <b>«↻ Перегенерировать»</b> или <b>«🗑 Удалить»</b> (уйдёт в архив, не пропадёт).</p>
        <p><b>Галочка «Сложный наряд»</b> нужна для костюмов с мелкими деталями (гравировка, узор, пряжки):
          она добавляет кадр <b>в профиль</b> и блок <b>«Детали костюма»</b> с макро-планами. Для простой
          одежды её можно не включать.</p>
      </Help>

      {/* outfit tabs */}
      <div className="otabs">
        {OUTFITS.map((o) => (
          <button key={o.id} className={"otab" + (o.id === activeOutfit ? " on" : "") + (o.base ? " base" : "")}
            onClick={() => setActiveOutfit(o.id)}>
            <span className="otab-nm">{o.name}</span>
            {o.base ? <span className="badge lock" style={{ fontSize: 9 }}>🔒 база</span>
              : o.done ? <span className="badge done" style={{ fontSize: 9 }}>✓ готов</span>
                : <span className="badge now" style={{ fontSize: 9 }}>не снят</span>}
          </button>
        ))}
        <button className="otab add" title="Наряды добавляются в анкете героя">+ наряд</button>
      </div>

      {outfit.base ? (
        <Panel title={outfit.name} icon="👕" className="grey" badge={<span className="badge lock">🔒 снят на паспорте</span>}>
          <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>Это «привычный» костюм героя — он уже зафиксирован кадрами паспорта. Отдельно снимать не нужно. Здесь — только для справки.</p>
          <PromptField value={outfit.prompt} readOnly rows={1} layer="Одежда" />
          <div className="btnrow" style={{ marginTop: 14 }}>
            <button className="btn primary" onClick={() => setActiveOutfit("parade")}>Перейти к первому доп. наряду →</button>
          </div>
        </Panel>
      ) : (
        <OutfitBuilder key={outfit.id} ctx={ctx} outfit={outfit} complex={complex} setComplex={setComplex}
          details={details} setDetails={setDetails} states={states} setStates={setStates}
          archived={archived} archiveFrame={archiveFrame} onCardState={onCardState} />
      )}
    </div>
  );
}

/* builder body for one (non-base) outfit */
function OutfitBuilder({ ctx, outfit, complex, setComplex, details, setDetails, states, onCardState, archived, archiveFrame }) {
  const BODY_SCENE = "Full-length character reference, head-to-toe, standing straight, both feet flat on the ground, plain neutral grey background, soft even lighting.";
  const frames = [
    { key: "front", title: "Фас, рост", fig: "front-full", req: true, scene: BODY_SCENE, initial: states.front },
    { key: "back", title: "Спина, рост", fig: "back-full", req: true, scene: "Full-length character reference seen from behind, back view, head-to-toe, both feet flat on the ground, plain neutral grey background.", initial: states.back }];
  if (complex) frames.push({ key: "profile", title: "Профиль, рост", fig: "profile-portrait", req: false, scene: "Full-length character reference, strict side profile, head-to-toe, both feet flat on the ground, plain neutral grey background.", initial: states.profile });

  const missing = frames.filter((f) => f.req && states[f.key] !== "ready");
  const canNext = ["front", "back"].every((k) => states[k] === "ready");
  function genMissing() {missing.forEach((f) => f._gen && f._gen());}

  return (
    <div>
      <Panel title="Описание наряда" icon="🧥">
        <Field ru="Одежда" en="OUTFIT" hint={<DoDont yes="одежду, доспех, материал, крой, цвет" no="телосложение, лицо, эмоцию, позу/ракурс/фон" />}>
          <PromptField value={outfit.prompt} rows={2} layer="Одежда" />
        </Field>
        <div className="notice" style={{ marginTop: 4, marginBottom: 14 }}>
          <span className="ic">📏</span>
          <span className="tx">Важно получить героя в <b>полный рост без обрезки</b> — от макушки до обуви целиком в кадре.</span>
        </div>
        <label className={"toggle" + (complex ? " on" : "")} onClick={(e) => {e.preventDefault();setComplex(!complex);}}>
          <span className="tr"></span>
          <span style={{ fontWeight: 700, fontSize: 14 }}>Сложный наряд</span>
          <span className="muted" style={{ fontSize: 12.5, marginLeft: 4 }}>— включите для костюмов с мелкими деталями: добавит кадр в профиль + блок «Детали костюма»</span>
        </label>
      </Panel>

      <Panel title="Кадры наряда" icon="🖼">
        <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>У каждого кадра — своя генерация и своя сцена. <span style={{ color: "var(--red)" }}>*</span> — обязательные.</p>
        <div className="pv-grid" style={{ gridTemplateColumns: complex ? "repeat(3,1fr)" : "repeat(2,1fr)" }}>
          {frames.map((f) => <SceneCard key={f.key} frame={f} onStateChange={onCardState} onArchive={archiveFrame} />)}
        </div>
        {archived > 0 && <p className="muted" style={{ fontSize: 12, marginTop: 12, marginBottom: 0 }}>🗑 Отправлено в архив за эту сессию: <b>{archived}</b> — лежат в папке <span className="mono">rejected/</span>.</p>}
      </Panel>


      {complex &&
      <Panel title="Детали костюма" icon="🔍" badge={<span className="badge opt">крупный план</span>}>
          <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>Макро-кадр детали (узор, пряжка, гравировка). Герой тут не нужен — только костюм и стиль.</p>
          <Help title="Из чего собирается промт?" defaultOpen={false}>
            <p>Чтобы деталь была <b>в том же стиле и из того же костюма</b>, ИИ собирает промт из слоёв:
              <b> стиль</b> (манера рисунка) + <b>костюм</b> (материал, цвет) + <b>ваша деталь</b> +
              <b> макро-рамка</b> (крупный план, чистый фон, свет) и запрет рисовать человека.</p>
            <p>Вам достаточно описать <b>только саму деталь</b> — остальное подставится автоматически.
              Кнопка <b>✦ Собрать промт</b> отдаёт это ИИ, чтобы он аккуратно свёл всё в один кадр.</p>
          </Help>
          {details.map((d, i) =>
        <div className="panel soft" key={d.id} style={{ marginBottom: 12 }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 130px", gap: 14, alignItems: "start" }}>
                <div>
                  <Field ru={"Деталь " + (i + 1)} en="" hint={<DoDont yes="что за деталь крупным планом: гравировка, пряжка, узор" no="лицо/тело героя, позу, фон" />}>
                    <PromptField value={d.prompt} rows={2} layer="Деталь" />
                  </Field>
                  <div className="assembled">
                    <div className="assembled-h">Сборный промт кадра <span className="muted" style={{ fontWeight: 400 }}>— подставляется автоматически</span></div>
                    <div className="chiprow">
                      <span className="pchip style">стиль: ink line + watercolour</span>
                      <span className="pchip outfit">костюм: ornate plate armor, crimson cloak</span>
                      <span className="pchip detail">деталь: {d.prompt || "—"}</span>
                      <span className="pchip frame">макро: close-up, product shot, plain bg, soft light</span>
                      <span className="pchip excl">без человека / лица / рук</span>
                    </div>
                  </div>
                  <div className="btnrow" style={{ marginTop: 10 }}>
                    <button className="btn sm">Сгенерировать</button>
                    <AIButton small onClick={() => {}}>Собрать промт</AIButton>
                    <button className="btn warn sm" onClick={() => setDetails(details.filter((x) => x.id !== d.id))}>Удалить</button>
                  </div>
                </div>
                <div className="pv-col">
                  <div className="pv-title">превью</div>
                  <div className="pv empty" style={{ minHeight: 100 }}><Figure kind="item" size={36} /></div>
                </div>
              </div>
            </div>
        )}
          <div className="addrow" style={{ padding: 10, border: "1.5px dashed var(--line-2)", borderRadius: 8 }} onClick={() => setDetails([...details, { id: Date.now(), prompt: "", st: "empty" }])}>+ добавить деталь</div>
        </Panel>
      }

      <div style={{ marginTop: 22 }}>
        {!canNext &&
        <div className="notice" style={{ marginBottom: 14 }} data-comment-anchor="3096dd5728-div-155-9">
            <span className="ic">⏭</span>
            <span className="tx">Пока не сгенерированы <b>Фас</b> и <b>Спина</b> в полный рост, система не сможет использовать
              этот наряд для героя — <b>при выгрузке он будет пропущен</b>. Можно догенерить недостающее или пропустить наряд.</span>
            <button className="btn sm" style={{ marginLeft: "auto", whiteSpace: "nowrap" }} onClick={genMissing}>Сгенерировать недостающие</button>
          </div>
        }
        <div className="btnrow split">
          <button className="btn ghost" onClick={() => ctx.go("emotions")}>← Назад</button>
          {canNext
            ? <button className="btn approve" onClick={() => ctx.go("props")}>Согласовать наряд →</button>
            : <button className="btn warn" onClick={() => ctx.go("props")} title="Наряд без фас+спины будет пропущен при выгрузке">Пропустить наряд →</button>}
        </div>
      </div>
    </div>);

}

/* =========================================================
   PROPS SCREEN
   ========================================================= */
function PropShot({ n, total, what, prompt, initial, onDelete }) {
  const [st, setSt] = useS3(initial || "empty");
  function gen() {if (window.__bumpCost) window.__bumpCost(8);
    if (window.setLastGen) window.setLastGen({ section: "Предмет", view: what || ("кадр " + n),
      layers: {
        style: "graphic novel, bold ink linework, muted watercolour wash, dramatic chiaroscuro lighting",
        item: prompt,
        composition: "product shot, centered, plain neutral background, soft even studio lighting" },
      refs: [{ label: "стиль-реф", kind: "item" }],
      model: "nano-banana", size: "1024×1024" });
    setSt("gen");setTimeout(() => setSt("ready"), 1000);}
  return (
    <Panel className="soft" marks={false}>
      <div className="panel-h" style={{ marginBottom: 12 }}>
        <span className="ttl" style={{ fontSize: 16 }}>Кадр {n}</span>
        <span className="badge ro">{n} / {total} (макс. 3)</span>
        <span className="spacer"></span>
      </div>
      <Field ru="Что это (своими словами)">
        <input className="in" defaultValue={what} placeholder="например: общий вид меча, клинок целиком" />
      </Field>
      <Field ru="Описание кадра" en="prompt" hint={<DoDont yes="предмет/эффект, материал, форму, «product shot», чистый фон" no="героя (лицо, тело, руки), сцену, кто держит" />}>
        <PromptField value={prompt} rows={2} layer="Предмет" />
      </Field>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 140px", gap: 14, alignItems: "start" }}>
        <div className="btnrow">
          <button className="btn sm" onClick={gen}>{st === "ready" ? "↻ Заново" : "Сгенерировать"}</button>
          <button className="btn warn sm" onClick={onDelete}>Удалить кадр</button>
        </div>
        <div className="pv empty" style={{ minHeight: 96 }}>
          {st === "gen" ? <div className="pv-spin"></div> : <><Figure kind="item" size={34} />{st === "ready" && <span className="pv-sub" style={{ color: "var(--green)" }}>✓ готово</span>}</>}
        </div>
      </div>
    </Panel>);

}

function ScreenProps({ ctx }) {
  // multiple items (from the анкета). Each has its own shots.
  const ITEMS = [
    { id: "sword", name: "Меч «Атлантида»", accent: "Меч «Атлантида»",
      shots: [
        { id: 1, what: "общий вид меча, клинок целиком", prompt: "ancient bronze longsword, ornate hilt, runic engravings, product shot, plain neutral background", initial: "ready" },
        { id: 2, what: "крупный план рукояти и руны", prompt: "close-up of the sword hilt, glowing runes, product shot", initial: "empty" }] },
    { id: "fire", name: "Огненная магия", accent: "Огненная магия",
      shots: [
        { id: 1, what: "огненный каст, общий вид", prompt: "burst of magical fire, swirling embers, dramatic lighting, plain dark background, no character", initial: "empty" }] },
  ];
  const [activeItem, setActiveItem] = useS3("sword");
  const item = ITEMS.find((x) => x.id === activeItem) || ITEMS[0];

  const [finish, setFinish] = useS3(null);
  function doFinish() {
    const res = window.downloadHeroArchive ? window.downloadHeroArchive(ctx.activeChar) : { approved: 0, rejected: 0 };
    setFinish(res);
  }
  return (
    <div>
      <div className="eyebrow">Шаг 5 из 6 · Предметы · по желанию · финал</div>
      <h1 className="pagetitle">Предметы героя <span className="accent">{ctx.activeChar}</span></h1>
      <p className="kicker">Снимем фирменное оружие, артефакты и магические эффекты — «как в каталоге», на чистом фоне. Так предмет будет выглядеть одинаково в любой сцене. Героя тут нет — только сам предмет. Выберите предмет вкладкой ниже.</p>

      <Help title="Чем предмет отличается от наряда?">
        <p>Предмет рисуется <b>без человека</b> — это просто эталон вещи или эффекта (меч, амулет, огненный
          каст магии). Каждый предмет собирается отдельно — переключайтесь вкладками. На предмет можно
          сделать от 1 до 3 кадров: общий вид и пару крупных планов.</p>
        <p>Магия и эффекты — сюда же: в описании пишете эффект, а не предмет.</p>
      </Help>

      {/* item tabs */}
      <div className="otabs">
        {ITEMS.map((it) => (
          <button key={it.id} className={"otab" + (it.id === activeItem ? " on" : "")} onClick={() => setActiveItem(it.id)}>
            <span className="otab-nm">{it.name}</span>
            <span className="badge ro" style={{ fontSize: 9 }}>{it.shots.filter((s) => s.initial === "ready").length}/{it.shots.length} кадр.</span>
          </button>
        ))}
        <button className="otab add" title="Предметы добавляются в анкете героя">+ предмет</button>
      </div>

      <PropBuilder key={item.id} item={item} />

      <div className="btnrow split" style={{ marginTop: 12 }}>
        <button className="btn ghost" onClick={() => ctx.go("outfit")}>← Назад</button>
        <button className="btn approve" onClick={doFinish}>Завершить героя и скачать архив ⬇</button>
      </div>

      {finish &&
      <Dialog onClose={() => setFinish(null)}>
          <h3>✓ Готово! Архив скачивается</h3>
          <p>Собрали всё по герою <b>{ctx.activeChar}</b> в один ZIP-архив — он уже загружается в папку
            «Загрузки». Если скачивание не началось, нажмите кнопку ниже.</p>
          <div className="panel soft" style={{ marginBottom: 14 }}>
            <div className="mono" style={{ fontSize: 12.5, lineHeight: 1.7 }}>
              📦 {ctx.activeChar}_паспорт.zip<br />
              ├── <b>passport.json</b> <span className="muted">— все промты по слоям</span><br />
              ├── 📁 approved/ <span className="muted">— {finish.approved} одобренных кадров</span><br />
              │&nbsp;&nbsp;&nbsp;&nbsp;<span className="muted">01_passport_face_gen2 · 02_passport_body_gen1 …</span><br />
              └── 📁 rejected/ <span className="muted">— {finish.rejected} в архиве (с номером генерации)</span><br />
              &nbsp;&nbsp;&nbsp;&nbsp;<span className="muted">rej_01_passport_profile_gen1 …</span>
            </div>
          </div>
          <div className="btnrow split">
            <button className="btn sm" onClick={doFinish}>⬇ Скачать ещё раз</button>
            <button className="btn primary sm" onClick={() => {setFinish(null);ctx.go("start");}}>На главную →</button>
          </div>
        </Dialog>
      }
    </div>);

}

/* builder body for one item (its shots) */
function PropBuilder({ item }) {
  const [shots, setShots] = useS3(item.shots);
  return (
    <div>
      {shots.map((s, i) =>
      <PropShot key={s.id} n={i + 1} total={shots.length} what={s.what} prompt={s.prompt} initial={s.initial}
      onDelete={() => setShots(shots.filter((x) => x.id !== s.id))} />
      )}
      {shots.length < 3 ?
      <div className="addrow" style={{ padding: 12, border: "1.5px dashed var(--line-2)", borderRadius: 8, marginBottom: 20 }} onClick={() => setShots([...shots, { id: Date.now(), what: "", prompt: "", initial: "empty" }])}>+ добавить кадр</div> :

      <p className="muted center" style={{ fontSize: 12.5 }}>Достигнут максимум — 3 кадра на предмет.</p>
      }
    </div>);
}

/* =========================================================
   DATASET SCREEN — automatic batch collection
   ========================================================= */
const POSE_LABELS = [
"идёт, таверна", "сидит у костра", "стоит, вид сверху", "бой, замах мечом",
"облокотился на стену", "смотрит вдаль, скала", "бежит, лес", "присел, низкий ракурс",
"разговор, в профиль", "верхом на коне", "крупный план, дождь", "спиной, на мосту",
"руки скрещены, рынок", "падает на колени", "со спины, закат", "прыжок через пропасть",
"у костра ночью", "в дверном проёме", "на троне", "ползёт в темноте",
"вид сбоку, ходьба", "оборачивается", "под аркой", "на крыше, ветер"];

const POSE_FIGS = ["threeq-full", "front-full", "back-full", "profile-portrait"];

function ScreenDataset({ ctx }) {
  const [phase, setPhase] = useS3("setup"); // setup | running | done
  const [count, setCount] = useS3(16);
  const [filled, setFilled] = useS3(0); // how many tiles generated so far
  const [verdict, setVerdict] = useS3({}); // index -> "approved" | "rejected"
  const timer = React.useRef(null);

  function start() {
    if (window.__bumpCost) window.__bumpCost(count * 8);
    setPhase("running");setFilled(0);setVerdict({});
    timer.current = setInterval(() => {
      setFilled((f) => {
        const nf = f + 1;
        if (nf >= count) {clearInterval(timer.current);setPhase("done");}
        return nf;
      });
    }, 180);
  }
  React.useEffect(() => () => clearInterval(timer.current), []);

  function setV(i, v) {setVerdict((m) => ({ ...m, [i]: m[i] === v ? undefined : v }));}
  const approvedN = Object.values(verdict).filter((v) => v === "approved").length;
  const rejectedN = Object.values(verdict).filter((v) => v === "rejected").length;

  const tiles = Array.from({ length: count }, (_, i) => i);

  return (
    <div>
      <div className="eyebrow">Шаг 6 из 7 · Финал · автосбор</div>
      <h1 className="pagetitle">Автосбор кадров <span className="accent">для сцен</span></h1>
      <p className="kicker">Дальше работает нейросеть. Лицо, тело и наряд уже закреплены — поэтому она сама
        нагенерит пачку кадров героя в <b>случайных позах и местах</b>, а вам останется только разобрать
        результат: что-то оставить, что-то в архив.</p>

      <Help title="Что сейчас произойдёт?">
        <p>Вы задаёте, <b>сколько кадров</b> набрать, и жмёте «Запустить». Нейросеть сама придумывает позы,
          ракурсы и фоны и рисует кадры один за другим — <b>вручную ничего описывать не нужно</b>.</p>
        <p>Когда пачка готова — пройдитесь по превью: нажмите <b>✓</b> на удачных (уйдут в готовые) и
          <b> ✕</b> на неудачных (уйдут в архив). Можно ничего не нажимать — кадры просто останутся.</p>
      </Help>

      {/* locked-in summary — always visible */}
      <Panel className="soft" marks={false}>
        <div className="field-lbl" style={{ marginBottom: 10 }}><span className="ru">Что нейросеть держит постоянным</span><span className="badge lock" style={{ marginLeft: 8 }}>🔒 закреплено</span></div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", fontSize: 12.5 }}>
          <span className="pchip detail">герой: {ctx.activeChar} (рефы паспорта)</span>
          <span className="pchip outfit">наряд: парадный доспех</span>
          <span className="pchip style">эмоция: grim, brooding</span>
          <span className="pchip frame">позы и фон: придумывает ИИ</span>
        </div>
      </Panel>

      {phase === "setup" &&
      <Panel title="Сколько кадров набрать?" icon="🎲">
          <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>Чем больше — тем дольше и дороже. Можно начать с малого и потом догенерить ещё.</p>
          <div className="btnrow" style={{ gap: 8, marginBottom: 14 }}>
            {[8, 16, 24, 40].map((n) =>
          <button key={n} className={"btn sm " + (count === n ? "primary" : "ghost")} onClick={() => setCount(n)}>{n} кадров</button>
          )}
          </div>
          <div className="notice" style={{ marginBottom: 16 }}>
            <span className="ic">💰</span>
            <span className="tx">Это <b>{count}</b> платных генераций — ориентировочно <b>≈ {count * 8} ₽</b> за пачку. Сумма прибавится к счётчику сессии.</span>
          </div>
          <div className="btnrow split">
            <button className="btn ghost" onClick={() => ctx.go("props")}>← Назад</button>
            <button className="btn primary" onClick={start}>▶ Запустить автосбор ({count})</button>
          </div>
        </Panel>
      }

      {phase !== "setup" &&
      <Panel marks={true}>
          <div className="panel-h">
            <span className="ttl" style={{ fontSize: 18 }}>{phase === "running" ? "Нейросеть набирает кадры…" : "Пачка готова — разберите"}</span>
            <span className="spacer"></span>
            {phase === "running" ?
          <span className="badge now">{filled} / {count}</span> :
          <span className="badge done">✓ {count} кадров</span>}
          </div>

          {/* progress bar */}
          <div className="progress" style={{ marginBottom: 16 }}>
            <div className="progress-fill" style={{ width: Math.min(filled, count) / count * 100 + "%" }}></div>
          </div>

          <div className="pv-grid" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
            {tiles.map((i) => {
            const done = i < filled;
            const v = verdict[i];
            return (
              <div key={i} className={"pv " + (!done ? "gen" : v === "rejected" ? "empty" : "ready")} style={{ minHeight: 150, opacity: done && v === "rejected" ? 0.5 : 1 }}>
                  {!done ? <div className="pv-spin"></div> :
                <>
                      {v && <span className="pv-badge"><span className={"badge " + (v === "approved" ? "done" : "ro")}>{v === "approved" ? "✓ готов" : "✕ архив"}</span></span>}
                      <Figure kind={POSE_FIGS[i % POSE_FIGS.length]} size={52} />
                      <span className="pv-sub">{POSE_LABELS[i % POSE_LABELS.length]}</span>
                      <div className="tile-acts">
                        <button className={"tact ap" + (v === "approved" ? " on" : "")} title="В готовые" onClick={() => setV(i, "approved")}>✓</button>
                        <button className={"tact rj" + (v === "rejected" ? " on" : "")} title="В архив" onClick={() => setV(i, "rejected")}>✕</button>
                      </div>
                    </>
                }
                </div>);

          })}
          </div>

          {phase === "done" &&
        <div className="btnrow" style={{ marginTop: 16 }}>
              <button className="btn ghost sm" onClick={() => setPhase("setup")}>↻ Набрать ещё пачку</button>
              <span className="muted" style={{ fontSize: 12.5, alignSelf: "center" }}>Наведите на кадр и отметьте ✓ или ✕. Неотмеченные просто останутся в общей папке.</span>
            </div>
        }
        </Panel>
      }

      <Panel title="Готово и архив" icon="📦" className="soft">
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
          <div><span className="badge done">approved/</span> <span className="muted" style={{ fontSize: 13 }}>одобренные — {approvedN}</span></div>
          <div><span className="badge ro">rejected/</span> <span className="muted" style={{ fontSize: 13 }}>в архиве — {rejectedN}</span></div>
          <div><span className="badge opt">всего собрано</span> <span className="muted" style={{ fontSize: 13 }}>{phase === "setup" ? 0 : filled}</span></div>
        </div>
      </Panel>

      <div className="btnrow split" style={{ marginTop: 18 }}>
        <button className="btn ghost" onClick={() => ctx.go("props")}>← Назад</button>
        <button className="btn go" onClick={() => ctx.go("start")}>Завершить героя ✓</button>
      </div>
    </div>);

}

window.ScreenOutfit = ScreenOutfit;
window.ScreenProps = ScreenProps;
window.ScreenDataset = ScreenDataset;
