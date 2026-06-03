/* global React, Panel, Help, Field, DoDont, PromptField, Preview, AIButton, Check, Toggle, Dialog, Figure, AdvancedScene, SceneModal */
const { useState: useS3 } = React;

/* =========================================================
   SCENE CARD — preview + own generate + edit-scene + approve
   ========================================================= */
function SceneCard({ id, index, scene, label, fig, req, getGen, onUpdate, register }) {
  const has = scene && scene.has_image;
  const [st, setSt] = useS3(has ? "ready" : "empty");
  const [v, setV] = useS3(0);
  React.useEffect(() => { setSt(scene && scene.has_image ? "ready" : "empty"); }, [scene && scene.has_image]);

  async function gen() {
    if (window.__bumpCost) window.__bumpCost(8);
    if (!id || !scene) { setSt("gen"); await new Promise((r) => setTimeout(r, 1000)); setSt("ready"); return; }
    setSt("gen");
    try {
      const d = await window.api.outfitGenerate(id, { index, scene: scene.scene, prompt: getGen ? getGen() : undefined });
      setV((x) => x + 1);
      setSt(d.ok ? "ready" : "empty");
      onUpdate && d.outfits && onUpdate(d.outfits);
    } catch (e) { setSt("empty"); }
  }
  // expose gen() so the parent can "догенерить недостающие"
  React.useEffect(() => { register && scene && register(scene.scene, gen); });

  const imgSrc = id && scene && st === "ready" ? window.api.imageUrl(id, scene.step_key, v, 400) : null;
  return (
    <div className="pv-col">
      <div className="pv-title">{label}{req && <span style={{ color: "var(--red)" }}> *</span>}</div>
      <div className={"pv " + (st === "ready" ? "ready" : st === "gen" ? "gen" : "empty")} style={{ minHeight: 160 }}>
        {st === "gen" ? <div className="pv-spin"></div> :
          st === "ready" ? <><span className="pv-badge"><span className="badge done">✓</span></span>{imgSrc ? <img src={imgSrc} alt={label} style={{ maxWidth: "100%", maxHeight: 140, borderRadius: 6, objectFit: "contain" }} onError={(e) => { e.target.style.display = "none"; }} /> : <Figure kind={fig} size={62} />}</> :
            <><Figure kind={fig} size={62} /><span className="pv-sub" style={{ color: req ? "var(--red)" : "var(--ink-3)" }}>{req ? "нужен этот кадр" : "нет кадра"}</span></>}
      </div>
      {st === "ready" ?
        <button className="btn sm" onClick={gen} style={{ width: "100%" }}>↻ Перегенерировать</button> :
        <button className="btn sm" onClick={gen} style={{ width: "100%" }}>Сгенерировать</button>}
    </div>);
}

const SCENE_META = {
  front_full: { label: "Фас, рост", fig: "front-full", req: true },
  back_full: { label: "Спина, рост", fig: "back-full", req: true },
  profile_full: { label: "Профиль, рост", fig: "profile-portrait", req: false },
};

/* sample outfits payload for the static preview (no backend) */
const SAMPLE_OUTFITS = {
  enabled: true,
  base_outfit: "dark fur-trimmed leather tunic, wide leather belt",
  outfits: [
    { index: 0, id: "1", name: "ornate ceremonial plate armor, engraved pauldrons, crimson cloak", complex: true,
      scenes: [{ scene: "front_full", step_key: "", has_image: false, approved: false }, { scene: "back_full", step_key: "", has_image: false, approved: false }, { scene: "profile_full", step_key: "", has_image: false, approved: false }],
      details: [], required_present: false },
    { index: 1, id: "2", name: "worn travelling cloak, hood, leather satchel", complex: false,
      scenes: [{ scene: "front_full", step_key: "", has_image: false, approved: false }, { scene: "back_full", step_key: "", has_image: false, approved: false }],
      details: [], required_present: false },
  ],
  all_approved: false, missing: [],
};

function ScreenOutfit({ ctx }) {
  const id = ctx.activeCharId;
  const [out, setOut] = useS3(null);
  const [activeIdx, setActiveIdx] = useS3(0); // -1 = base tab, else outfit index

  React.useEffect(() => {
    if (!id) { setActiveIdx(0); return; }
    let alive = true;
    window.api.getOutfits(id).then((d) => {
      if (alive && d && d.outfits) { setOut(d.outfits); setActiveIdx(d.outfits.outfits.length ? 0 : -1); }
    }).catch(() => {});
    return () => { alive = false; };
  }, [id]);

  const data = out || SAMPLE_OUTFITS;
  const outfits = data.outfits;

  return (
    <div>
      <div className="eyebrow">Шаг 4 из 6 · Наряды · по желанию</div>
      <h1 className="pagetitle">Наряды героя <span className="accent">{ctx.activeChar}</span></h1>
      <p className="kicker">У героя может быть несколько костюмов — выберите наряд вкладкой ниже и снимите его с нужных сторон. Лицо и тело уже заморожены, меняется только одежда.</p>

      <Help title="Что это за вкладки нарядов?">
        <p>Наряды вы перечислили в анкете героя. Здесь каждый <b>собирается отдельно</b> — переключайтесь
          вкладками. <b>Базовый костюм</b> уже снят на шаге паспорта, поэтому он только для справки (🔒).</p>
        <p>Для каждого наряда нужны минимум <b>Фас</b> и <b>Спина</b> <span style={{ color: "var(--red)" }}>*</span>.
          Не нравится кадр — <b>«↻ Перегенерировать»</b> (прошлый уйдёт в архив, не пропадёт).</p>
        <p><b>Галочка «Сложный наряд»</b> нужна для костюмов с мелкими деталями (гравировка, узор, пряжки):
          она добавляет кадр <b>в профиль</b> и блок <b>«Детали костюма»</b> с макро-планами. Для простой
          одежды её можно не включать.</p>
      </Help>

      {/* outfit tabs */}
      <div className="otabs">
        <button className={"otab base" + (activeIdx === -1 ? " on" : "")} onClick={() => setActiveIdx(-1)}>
          <span className="otab-nm">Базовый костюм</span><span className="badge lock" style={{ fontSize: 9 }}>🔒 база</span>
        </button>
        {outfits.map((o, i) => (
          <button key={o.id} className={"otab" + (i === activeIdx ? " on" : "")} onClick={() => setActiveIdx(i)}>
            <span className="otab-nm">{o.name || ("наряд " + o.id)}</span>
            {o.required_present ? <span className="badge done" style={{ fontSize: 9 }}>✓ готов</span> : <span className="badge now" style={{ fontSize: 9 }}>не снят</span>}
          </button>
        ))}
        <button className="otab add" title="Наряды добавляются в анкете героя">+ наряд</button>
      </div>

      {activeIdx === -1 ? (
        <Panel title="Базовый костюм" icon="👕" className="grey" badge={<span className="badge lock">🔒 снят на паспорте</span>}>
          <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>Это «привычный» костюм героя — он уже зафиксирован кадрами паспорта. Отдельно снимать не нужно. Здесь — только для справки.</p>
          <PromptField value={data.base_outfit} readOnly rows={1} layer="Одежда" />
          <div className="btnrow" style={{ marginTop: 14 }}>
            {outfits.length > 0 && <button className="btn primary" onClick={() => setActiveIdx(0)}>Перейти к первому доп. наряду →</button>}
          </div>
        </Panel>
      ) : outfits[activeIdx] ? (
        <OutfitBuilder key={outfits[activeIdx].id} ctx={ctx} id={id} outfit={outfits[activeIdx]} onUpdate={setOut} />
      ) : (
        <Panel><p className="center muted" style={{ padding: 30 }}>Нет дополнительных нарядов — их добавляют в анкете героя.</p></Panel>
      )}
    </div>
  );
}

/* builder body for one (non-base) outfit */
function OutfitBuilder({ ctx, id, outfit, onUpdate }) {
  const [prompt, setPrompt] = useS3(outfit.name || "");
  React.useEffect(() => { setPrompt(outfit.name || ""); }, [outfit.id]);
  const genFns = React.useRef({});
  function register(scene, fn) { genFns.current[scene] = fn; }

  const front = outfit.scenes.find((s) => s.scene === "front_full");
  const back = outfit.scenes.find((s) => s.scene === "back_full");
  const canNext = !!(front && front.has_image) && !!(back && back.has_image);
  const missing = outfit.scenes.filter((s) => SCENE_META[s.scene] && SCENE_META[s.scene].req && !s.has_image);
  function genMissing() { missing.forEach((s) => { const fn = genFns.current[s.scene]; fn && fn(); }); }

  async function toggleComplex() {
    if (!id) return;
    try { const d = await window.api.outfitComplex(id, outfit.index, !outfit.complex); onUpdate && d.outfits && onUpdate(d.outfits); } catch (e) { /* ignore */ }
  }
  async function approveNext() {
    if (id && canNext) { try { await window.api.outfitApprove(id, outfit.index); } catch (e) { /* ignore */ } }
    ctx.go("props");
  }

  return (
    <div>
      <Panel title="Описание наряда" icon="🧥">
        <Field ru="Одежда" en="OUTFIT" hint={<DoDont yes="одежду, доспех, материал, крой, цвет" no="телосложение, лицо, эмоцию, позу/ракурс/фон" />}>
          <PromptField value={prompt} onChange={setPrompt} rows={2} layer="Одежда" />
        </Field>
        <div className="notice" style={{ marginTop: 4, marginBottom: 14 }}>
          <span className="ic">📏</span>
          <span className="tx">Важно получить героя в <b>полный рост без обрезки</b> — от макушки до обуви целиком в кадре. Описание применится при следующей генерации.</span>
        </div>
        <label className={"toggle" + (outfit.complex ? " on" : "")} onClick={(e) => { e.preventDefault(); toggleComplex(); }}>
          <span className="tr"></span>
          <span style={{ fontWeight: 700, fontSize: 14 }}>Сложный наряд</span>
          <span className="muted" style={{ fontSize: 12.5, marginLeft: 4 }}>— включите для костюмов с мелкими деталями: добавит кадр в профиль + блок «Детали костюма»</span>
        </label>
      </Panel>

      <Panel title="Кадры наряда" icon="🖼">
        <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>У каждого кадра — своя генерация. <span style={{ color: "var(--red)" }}>*</span> — обязательные (Фас и Спина).</p>
        <div className="pv-grid" style={{ gridTemplateColumns: outfit.complex ? "repeat(3,1fr)" : "repeat(2,1fr)" }}>
          {outfit.scenes.map((s) => {
            const m = SCENE_META[s.scene] || {};
            return <SceneCard key={s.scene} id={id} index={outfit.index} scene={s} label={m.label} fig={m.fig} req={m.req} getGen={() => prompt} onUpdate={onUpdate} register={register} />;
          })}
        </div>
      </Panel>

      {outfit.complex && <OutfitDetails id={id} outfit={outfit} onUpdate={onUpdate} />}

      <div style={{ marginTop: 22 }}>
        {!canNext &&
          <div className="notice" style={{ marginBottom: 14 }}>
            <span className="ic">⏭</span>
            <span className="tx">Пока не сгенерированы <b>Фас</b> и <b>Спина</b> в полный рост, система не сможет использовать
              этот наряд для героя — <b>при выгрузке он будет пропущен</b>. Можно догенерить недостающее или пропустить наряд.</span>
            <button className="btn sm" style={{ marginLeft: "auto", whiteSpace: "nowrap" }} onClick={genMissing}>Сгенерировать недостающие</button>
          </div>}
        <div className="btnrow split">
          <button className="btn ghost" onClick={() => ctx.go("emotions")}>← Назад</button>
          {canNext
            ? <button className="btn approve" onClick={approveNext}>Согласовать наряд →</button>
            : <button className="btn warn" onClick={() => ctx.go("props")} title="Наряд без фас+спины будет пропущен при выгрузке">Пропустить наряд →</button>}
        </div>
      </div>
    </div>);
}

/* costume-detail block for a complex outfit */
function OutfitDetails({ id, outfit, onUpdate }) {
  async function add() {
    if (!id) return;
    try { const d = await window.api.outfitDetail(id, "add", { index: outfit.index }); onUpdate && d.outfits && onUpdate(d.outfits); } catch (e) { /* ignore */ }
  }
  async function del(n) {
    if (!id) return;
    try { const d = await window.api.outfitDetail(id, "delete", { index: outfit.index, n: n }); onUpdate && d.outfits && onUpdate(d.outfits); } catch (e) { /* ignore */ }
  }
  return (
    <Panel title="Детали костюма" icon="🔍" badge={<span className="badge opt">крупный план</span>}>
      <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>Макро-кадр детали (узор, пряжка, гравировка). Герой тут не нужен — только костюм и стиль; промт собирается автоматически.</p>
      {outfit.details.map((d) => <OutfitDetailRow key={d.n} id={id} index={outfit.index} detail={d} onUpdate={onUpdate} onDelete={() => del(d.n)} />)}
      <div className="addrow" style={{ padding: 10, border: "1.5px dashed var(--line-2)", borderRadius: 8 }} onClick={add}>+ добавить деталь</div>
    </Panel>
  );
}

function OutfitDetailRow({ id, index, detail, onUpdate, onDelete }) {
  const [prompt, setPrompt] = useS3(detail.prompt || "");
  const [st, setSt] = useS3(detail.has_image ? "ready" : "empty");
  const [v, setV] = useS3(0);
  React.useEffect(() => { setSt(detail.has_image ? "ready" : "empty"); }, [detail.has_image]);
  async function gen() {
    if (window.__bumpCost) window.__bumpCost(8);
    if (!id) { setSt("gen"); await new Promise((r) => setTimeout(r, 1000)); setSt("ready"); return; }
    setSt("gen");
    try { const d = await window.api.outfitDetail(id, "generate", { index: index, n: detail.n, prompt: prompt }); setV((x) => x + 1); setSt(d.ok ? "ready" : "empty"); onUpdate && d.outfits && onUpdate(d.outfits); } catch (e) { setSt("empty"); }
  }
  const imgSrc = id && st === "ready" ? window.api.imageUrl(id, detail.step_key, v, 320) : null;
  return (
    <div className="panel soft" style={{ marginBottom: 12 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 130px", gap: 14, alignItems: "start" }}>
        <div>
          <Field ru={"Деталь " + detail.n} en="" hint={<DoDont yes="что за деталь крупным планом: гравировка, пряжка, узор" no="лицо/тело героя, позу, фон" />}>
            <PromptField value={prompt} onChange={setPrompt} rows={2} layer="Деталь" />
          </Field>
          <div className="btnrow" style={{ marginTop: 10 }}>
            <button className="btn sm" onClick={gen}>{st === "ready" ? "↻ Заново" : "Сгенерировать"}</button>
            <button className="btn warn sm" onClick={onDelete}>Удалить</button>
          </div>
        </div>
        <div className="pv-col">
          <div className="pv-title">превью</div>
          <div className={"pv " + (st === "ready" ? "ready" : st === "gen" ? "gen" : "empty")} style={{ minHeight: 100 }}>
            {st === "gen" ? <div className="pv-spin"></div>
              : imgSrc ? <img src={imgSrc} alt={"деталь " + detail.n} style={{ maxWidth: "100%", maxHeight: 90, borderRadius: 6, objectFit: "contain" }} onError={(e) => { e.target.style.display = "none"; }} />
                : <Figure kind="item" size={36} />}
          </div>
        </div>
      </div>
    </div>
  );
}

/* =========================================================
   PROPS SCREEN
   ========================================================= */
function PropShot({ id, index, shot, total, onUpdate, onDelete }) {
  const [what, setWhat] = useS3(shot.what || "");
  const [prompt, setPrompt] = useS3(shot.prompt || "");
  const [st, setSt] = useS3(shot.has_image ? "ready" : "empty");
  const [v, setV] = useS3(0);
  React.useEffect(() => { setSt(shot.has_image ? "ready" : "empty"); }, [shot.has_image]);
  async function gen() {
    if (window.__bumpCost) window.__bumpCost(8);
    if (!id) { setSt("gen"); await new Promise((r) => setTimeout(r, 1000)); setSt("ready"); return; }
    setSt("gen");
    try {
      const d = await window.api.propShot(id, "generate", { index: index, n: shot.n, what: what, prompt: prompt });
      setV((x) => x + 1);
      setSt(d.ok ? "ready" : "empty");
      onUpdate && d.props && onUpdate(d.props);
    } catch (e) { setSt("empty"); }
  }
  const imgSrc = id && st === "ready" ? window.api.imageUrl(id, shot.step_key, v, 320) : null;
  return (
    <Panel className="soft" marks={false}>
      <div className="panel-h" style={{ marginBottom: 12 }}>
        <span className="ttl" style={{ fontSize: 16 }}>Кадр {shot.n}</span>
        <span className="badge ro">{shot.n} / {total} (макс. 3)</span>
        <span className="spacer"></span>
      </div>
      <Field ru="Что это (своими словами)">
        <input className="in" value={what} onChange={(e) => setWhat(e.target.value)} placeholder="например: общий вид меча, клинок целиком" />
      </Field>
      <Field ru="Описание кадра" en="prompt" hint={<DoDont yes="предмет/эффект, материал, форму, «product shot», чистый фон" no="героя (лицо, тело, руки), сцену, кто держит" />}>
        <PromptField value={prompt} onChange={setPrompt} rows={2} layer="Предмет" />
      </Field>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 140px", gap: 14, alignItems: "start" }}>
        <div className="btnrow">
          <button className="btn sm" onClick={gen}>{st === "ready" ? "↻ Заново" : "Сгенерировать"}</button>
          <button className="btn warn sm" onClick={onDelete}>Удалить кадр</button>
        </div>
        <div className={"pv " + (st === "ready" ? "ready" : st === "gen" ? "gen" : "empty")} style={{ minHeight: 96 }}>
          {st === "gen" ? <div className="pv-spin"></div>
            : imgSrc ? <img src={imgSrc} alt={"кадр " + shot.n} style={{ maxWidth: "100%", maxHeight: 84, borderRadius: 6, objectFit: "contain" }} onError={(e) => { e.target.style.display = "none"; }} />
              : <><Figure kind="item" size={34} />{st === "ready" && <span className="pv-sub" style={{ color: "var(--green)" }}>✓ готово</span>}</>}
        </div>
      </div>
    </Panel>);
}

/* sample props payload for the static preview (no backend) */
const SAMPLE_PROPS = {
  enabled: true,
  items: [
    { index: 0, id: "1", name: "Меч «Атлантида»", shots: [
      { n: 1, what: "общий вид меча, клинок целиком", prompt: "ancient bronze longsword, ornate hilt, runic engravings, product shot, plain neutral background", step_key: "", has_image: false },
      { n: 2, what: "крупный план рукояти и руны", prompt: "close-up of the sword hilt, glowing runes, product shot", step_key: "", has_image: false }] },
    { index: 1, id: "2", name: "Огненная магия", shots: [
      { n: 1, what: "огненный каст, общий вид", prompt: "burst of magical fire, swirling embers, dramatic lighting, plain dark background, no character", step_key: "", has_image: false }] },
  ],
};

function ScreenProps({ ctx }) {
  const id = ctx.activeCharId;
  const [pr, setPr] = useS3(null);
  const [activeItem, setActiveItem] = useS3(0);
  const [finish, setFinish] = useS3(null);

  React.useEffect(() => {
    if (!id) return;
    let alive = true;
    window.api.getProps(id).then((d) => { if (alive && d && d.props) setPr(d.props); }).catch(() => {});
    return () => { alive = false; };
  }, [id]);

  const data = pr || SAMPLE_PROPS;
  const items = data.items;

  async function doFinish() {
    if (id) {
      try { await window.api.finishCharacter(id); } catch (e) { /* ignore */ }
      const a = document.createElement("a");
      a.href = window.api.archiveUrl(id);
      a.download = "";
      document.body.appendChild(a); a.click(); a.remove();
      setFinish({ real: true });
    } else {
      setFinish(window.downloadHeroArchive ? window.downloadHeroArchive(ctx.activeChar) : { approved: 0, rejected: 0 });
    }
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
        {items.map((it, i) => (
          <button key={it.id} className={"otab" + (i === activeItem ? " on" : "")} onClick={() => setActiveItem(i)}>
            <span className="otab-nm">{it.name || ("предмет " + it.id)}</span>
            <span className="badge ro" style={{ fontSize: 9 }}>{it.shots.filter((s) => s.has_image).length}/{it.shots.length} кадр.</span>
          </button>
        ))}
        <button className="otab add" title="Предметы добавляются в анкете героя">+ предмет</button>
      </div>

      {items[activeItem]
        ? <PropBuilder key={items[activeItem].id} id={id} item={items[activeItem]} onUpdate={setPr} />
        : <Panel><p className="center muted" style={{ padding: 30 }}>Нет предметов — их добавляют в анкете героя.</p></Panel>}

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
              📦 {ctx.activeChar}_passport.zip<br />
              ├── <b>passport.json</b> <span className="muted">— все промты по слоям</span><br />
              ├── 📁 approved/ <span className="muted">— одобренные кадры (золотой набор)</span><br />
              └── 📁 rejected/ <span className="muted">— архив отклонённых (с номером попытки)</span>
            </div>
          </div>
          <div className="btnrow split">
            <button className="btn sm" onClick={doFinish}>⬇ Скачать ещё раз</button>
            <button className="btn primary sm" onClick={() => { setFinish(null); ctx.go("start"); }}>На главную →</button>
          </div>
        </Dialog>}
    </div>);
}

/* builder body for one item (its shots) */
function PropBuilder({ id, item, onUpdate }) {
  async function add() {
    if (!id) return;
    try { const d = await window.api.propShot(id, "add", { index: item.index }); onUpdate && d.props && onUpdate(d.props); } catch (e) { /* ignore */ }
  }
  async function del(n) {
    if (!id) return;
    try { const d = await window.api.propShot(id, "delete", { index: item.index, n: n }); onUpdate && d.props && onUpdate(d.props); } catch (e) { /* ignore */ }
  }
  return (
    <div>
      {item.shots.map((s) =>
        <PropShot key={s.n} id={id} index={item.index} shot={s} total={item.shots.length} onUpdate={onUpdate} onDelete={() => del(s.n)} />)}
      {item.shots.length < 3
        ? <div className="addrow" style={{ padding: 12, border: "1.5px dashed var(--line-2)", borderRadius: 8, marginBottom: 20 }} onClick={add}>+ добавить кадр</div>
        : <p className="muted center" style={{ fontSize: 12.5 }}>Достигнут максимум — 3 кадра на предмет.</p>}
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
