/* global React, Panel, Help, Field, DoDont, PromptField, Preview, AIButton, Check, Toggle, Dialog, PresetPicker, Figure */
const { useState: useS1 } = React;

/* split «особые приметы» into face vs body marks by keyword (prototype heuristic) */
const FACE_WORDS = ["щек", "лиц", "лоб", "бров", "глаз", "нос", "губ", "борода", "усы", "щетин", "повязк", "шрам на лице", "родинк", "веснушк", "подбородок", "ухо", "уш"];
function faceMarks(s) {
  if (!s) return "";
  return s.split(/[,;]/).map((p) => p.trim()).filter((p) => p && FACE_WORDS.some((w) => p.toLowerCase().includes(w))).join(", ");
}
function bodyMarks(s) {
  if (!s) return "";
  return s.split(/[,;]/).map((p) => p.trim()).filter((p) => p && !FACE_WORDS.some((w) => p.toLowerCase().includes(w))).join(", ");
}

/* =========================================================
   SCREEN 1 — START
   ========================================================= */
const SAMPLE_STYLE = {
  prompt: "graphic novel, bold ink linework, muted watercolour wash, dramatic chiaroscuro lighting, grainy paper texture",
  approved: true, ref_keys: [], ref_count: 0, locked: false,
};

/* Downscale a picked image to <=maxSide px PNG before upload. The Space proxy
   drops upload bodies over ~2 MB, and full-res photos are bigger; a 1024px PNG
   stays well under that. Returns a PNG File (falls back to the original). */
function downscaleToPng(file, maxSide) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      const scale = Math.min(1, maxSide / Math.max(img.width, img.height));
      const w = Math.max(1, Math.round(img.width * scale));
      const h = Math.max(1, Math.round(img.height * scale));
      const canvas = document.createElement("canvas");
      canvas.width = w; canvas.height = h;
      canvas.getContext("2d").drawImage(img, 0, 0, w, h);
      canvas.toBlob((blob) => resolve(blob ? new File([blob], "ref.png", { type: "image/png" }) : file), "image/png");
    };
    img.onerror = () => { URL.revokeObjectURL(url); resolve(file); };
    img.src = url;
  });
}

function ScreenStart({ ctx }) {
  const [text, setText] = useS1("");
  const [extracted, setExtracted] = useS1(false);
  const [found, setFound] = useS1([]);
  const [saved, setSaved] = useS1(SAMPLE_CHARS);
  const [style, setStyle] = useS1(null);
  const [stylePrompt, setStylePrompt] = useS1("");
  const [styleBusy, setStyleBusy] = useS1(false);
  const [confirmReset, setConfirmReset] = useS1(false);

  // Bootstrap from the backend (session + saved characters + project style).
  // Degrades silently to sample data when no backend is present (static preview).
  React.useEffect(() => {
    let alive = true;
    window.api.session()
      .then((d) => { if (alive && Array.isArray(d.saved_characters)) setSaved(d.saved_characters); })
      .catch(() => {});
    window.api.getStyle()
      .then((d) => { if (alive && d.style) { setStyle(d.style); setStylePrompt(d.style.prompt || ""); } })
      .catch(() => { if (alive) { setStyle(SAMPLE_STYLE); setStylePrompt(SAMPLE_STYLE.prompt); } });
    return () => { alive = false; };
  }, []);

  // Attach one style reference FILE (multipart upload). The backend drafts the
  // prompt by LLM once the 5th lands; we reflect the returned style.
  async function onPickRef(e) {
    const file = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!file) return;
    setStyleBusy(true);
    try {
      const small = await downscaleToPng(file, 1024);
      const d = await window.api.styleRefs(small);
      if (d.style) { setStyle(d.style); setStylePrompt(d.style.prompt || ""); }
    } catch (err) { /* offline preview: ignore */ }
    setStyleBusy(false);
  }
  async function saveStylePrompt() {
    try { const d = await window.api.styleSave(stylePrompt); if (d.style) setStyle(d.style); } catch (e) { /* ignore */ }
  }
  async function resetStyle() {
    setConfirmReset(false);
    try { const d = await window.api.styleReset(); if (d.style) { setStyle(d.style); setStylePrompt(""); } }
    catch (e) { setStyle({ prompt: "", approved: false, ref_keys: [], ref_count: 0, locked: false }); setStylePrompt(""); }
  }

  // Paste -> real paid extraction. Returning the Promise keeps the AI button
  // shimmering for the true round-trip; a missing backend falls back to demo names.
  async function findHeroes() {
    try {
      const data = await window.api.extract(text);
      setFound((data.characters || []).map((c) => c.name));
    } catch (e) {
      setFound(["Герон", "Тайра", "Луций"]);
    }
    setExtracted(true);
  }

  // Pick a found hero -> create + persist the character server-side, then open
  // the anketa on its real id (degrades to name-only navigation with no backend).
  async function pickHero(name) {
    ctx.setActiveChar(name);
    try {
      const data = await window.api.createCharacter(name);
      ctx.setActiveCharId(data && data.character ? data.character.id : null);
    } catch (e) {
      ctx.setActiveCharId(null);
    }
    ctx.go("data");
  }

  return (
    <div>
      <div className="eyebrow">Шаг за шагом</div>
      <h1 className="pagetitle">Соберём <span className="accent">паспорт героя</span></h1>
      <p className="kicker">
        Это мастер: он проведёт вас за руку через всё создание персонажа для рисованной истории.
        Вы не пишете код и не разбираетесь в нейросетях — просто отвечаете на понятные вопросы и
        нажимаете «Дальше». В конце получите набор картинок одного героя со всех сторон.
      </p>

      <Help title="Как это вообще работает? (прочитайте 1 раз)">
        <p>Чтобы герой выглядел <b>одинаково</b> на каждой картинке, нейросети нужно показать «паспорт» —
          несколько эталонных портретов: лицо спереди, в профиль, в полный рост, со спины.</p>
        <p>Мы соберём их по шагам. Сначала закрепим <b>стиль рисунка</b> и <b>внешность</b> героя
          (лицо, тело) — это замораживается и больше не меняется. Потом добавим <b>одежду, эмоции,
          предметы</b> и в конце нагенерим много кадров для разных сцен.</p>
        <p>Все поля с английским текстом — это «команды» для нейросети. Их можно не сочинять с нуля:
          рядом всегда есть кнопка <b style={{ color: "var(--blue-deep)" }}>✦ помощь ИИ</b>, которая
          сама напишет или поправит текст.</p>
      </Help>

      {/* STYLE STEP */}
      {(() => {
        const st = style || SAMPLE_STYLE;
        const hasPrompt = !!st.prompt;
        const badge = !hasPrompt
          ? <span className="badge now">сначала это</span>
          : st.locked
            ? <span className="badge lock">🔒 закреплён</span>
            : <span className="badge now">черновик — можно править</span>;
        return (
          <Panel title="Стиль рисунка" icon="🎨" badge={badge}>
            <p className="muted" style={{ marginTop: 0, fontSize: 13.5 }}>
              Загрузите 5 примеров картинок в той манере, в которой хотите рисовать историю
              (комикс, акварель, нуар…). Когда прикрепите <b>5-й</b> — нейросеть сама опишет стиль
              словами, и дальше все картинки будут в этой манере.
            </p>

            {!hasPrompt && (
              <>
                <div className="pv-grid" style={{ gridTemplateColumns: "repeat(5,1fr)", marginBottom: 12 }}>
                  {[0, 1, 2, 3, 4].map((i) => (
                    i < st.ref_count
                      ? <div className="pv ready" key={i} style={{ minHeight: 92 }}>
                          {st.ref_keys[i] ? <img src={window.api.styleRefUrl(st.ref_keys[i], 240)} alt={"пример " + (i + 1)} onClick={() => window.__lightbox(window.api.styleRefUrl(st.ref_keys[i]))} style={{ maxWidth: "100%", maxHeight: 84, borderRadius: 6, objectFit: "cover", cursor: "zoom-in" }} onError={(e) => { e.target.style.display = "none"; }} /> : <Figure kind="item" size={34} />}
                          <span className="pv-sub">пример {i + 1}</span>
                        </div>
                      : <label className="pv" key={i} style={{ minHeight: 92, cursor: styleBusy ? "wait" : "pointer", borderStyle: "dashed" }}>
                          <input type="file" accept="image/*" style={{ display: "none" }} disabled={styleBusy} onChange={onPickRef} />
                          <Figure kind="item" size={26} />
                          <span className="pv-sub" style={{ color: "var(--blue-deep)" }}>+ пример {i + 1}</span>
                        </label>
                  ))}
                </div>
                {styleBusy
                  ? <p className="tip"><span className="ic">✦</span><span>{st.ref_count >= 4 ? "ИИ описывает стиль по референсам…" : "Загружаю…"}</span></p>
                  : <p className="tip"><span className="ic">ℹ</span><span>Прикреплено <b>{st.ref_count}</b> из 5. На пятом ИИ автоматически опишет стиль.</span></p>}
              </>
            )}

            {hasPrompt && (
              <>
                {st.ref_keys.length > 0 && (
                  <div className="pv-grid" style={{ gridTemplateColumns: "repeat(5,1fr)", marginBottom: 12 }}>
                    {st.ref_keys.map((key, i) => (
                      <div className="pv ready" key={key} style={{ minHeight: 80 }}>
                        <img src={window.api.styleRefUrl(key, 240)} alt={"пример " + (i + 1)} style={{ maxWidth: "100%", maxHeight: 72, borderRadius: 6, objectFit: "cover" }} onError={(e) => { e.target.style.display = "none"; }} />
                      </div>
                    ))}
                  </div>
                )}
                <Field ru="Описание стиля" en="STYLE" hint={<DoDont yes="манеру рисунка, технику, свет, палитру" no="конкретного героя, его лицо, одежду или сцену" />}>
                  <PromptField value={stylePrompt} onChange={setStylePrompt} readOnly={st.locked} rows={2} />
                </Field>
                <div className="btnrow" style={{ marginTop: 12 }}>
                  {st.locked
                    ? <span className="stamp lock">🔒 стиль закреплён</span>
                    : <button className="btn sm" onClick={saveStylePrompt}>Сохранить описание</button>}
                  {!st.locked && <span className="muted" style={{ fontSize: 12 }}>править можно, пока не сделан первый портрет</span>}
                  <span className="spacer" style={{ flex: 1 }}></span>
                  <button className="btn ghost sm" onClick={() => setConfirmReset(true)}>Изменить стиль</button>
                </div>
              </>
            )}
          </Panel>
        );
      })()}

      {/* STORY TEXT */}
      <Panel title="Текст вашей истории" icon="📖" badge={<span className="badge now">отсюда берём героев</span>}>
        <Help title="Зачем вставлять текст?" defaultOpen={false}>
          <p>Вставьте сюда отрывок сценария или книги. Нейросеть прочитает его и сама найдёт всех
            действующих героев — вам не придётся вписывать имена вручную. Дальше выберете, кого собирать.</p>
        </Help>
        <Field ru="Вставьте текст или загрузите файл">
          <textarea className="in" rows={5} placeholder="Например: «Герон вышел из таверны, поправил тяжёлый меч за спиной…»  — вставьте сюда главу или сцену." value={text} onChange={(e) => setText(e.target.value)} />
        </Field>
        <div className="btnrow split">
          <button className="btn ghost sm">📎 Загрузить файл (.txt, .docx)</button>
          <AIButton onClick={findHeroes}>Найти героев в тексте</AIButton>
        </div>

        {extracted && (
          <div className="panel soft" style={{ marginTop: 16, marginBottom: 0 }}>
            <div className="field-lbl"><span className="ru">Нашли героев</span></div>
            <div className="btnrow">
              {found.map((n) => (
                <button className="btn sm" key={n} onClick={() => pickHero(n)}>
                  <span className="av" style={{ width: 22, height: 22, borderRadius: 99, background: "var(--blue)", color: "#fff", display: "grid", placeItems: "center", fontSize: 11, fontWeight: 700 }}>{n[0]}</span>
                  {n} →
                </button>
              ))}
            </div>
            <p className="muted" style={{ fontSize: 12.5, marginTop: 12, marginBottom: 0 }}>Нажмите на героя, чтобы начать собирать его паспорт.</p>
          </div>
        )}
      </Panel>

      {/* SAVED CHARACTERS */}
      <Panel title="Сохранённые герои" icon="🗂" className="" badge={<span className="badge ro">из вашего архива</span>}>
        <p className="muted" style={{ marginTop: 0, fontSize: 13.5 }}>Можно вернуться к тому, кого уже начали. Мы откроем его ровно на том шаге, где вы остановились.</p>
        <table className="t">
          <thead><tr><th>Имя</th><th>Статус</th><th style={{ width: 230 }}></th></tr></thead>
          <tbody>
            {saved.map((c) => (
              <tr key={c.id}>
                <td style={{ fontWeight: 700 }}>{c.name}</td>
                <td>{c.status === "готов" ? <span className="badge done">✓ готов</span> : <span className="badge now">{c.status}</span>}</td>
                <td>
                  <div className="btnrow" style={{ justifyContent: "flex-end", gap: 8 }}>
                    {c.status === "готов" && (
                      <button className="btn ghost sm" title="Скачать ZIP-архив героя (кадры + промты)" onClick={() => { window.location.href = window.api.archiveUrl(c.id); }}>⬇ Скачать</button>
                    )}
                    <button className="btn ghost sm" onClick={() => { ctx.setActiveChar(c.name); ctx.setActiveCharId(c.id); ctx.go(c.step || "data"); }}>Открыть →</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      {confirmReset && (
        <Dialog onClose={() => setConfirmReset(false)}>
          <h3>⚠ Изменить стиль рисунка?</h3>
          <p>Стиль — общий для всех персонажей. Если поменять его сейчас, все уже нарисованные
            герои окажутся <b>не в том стиле</b> — их кадры придётся <b>перегенерировать заново</b>.</p>
          <p className="muted" style={{ fontSize: 13 }}>Текущее описание и референсы сбросятся, и вы загрузите 5 новых примеров.</p>
          <div className="btnrow end">
            <button className="btn ghost" onClick={() => setConfirmReset(false)}>Отмена</button>
            <button className="btn warn" onClick={resetStyle}>Да, изменить стиль</button>
          </div>
        </Dialog>
      )}
    </div>
  );
}

/* =========================================================
   SCREEN 2 — CHARACTER DATA (анкета)
   ========================================================= */
function ScreenData({ ctx }) {
  const [emoOn, setEmoOn] = useS1(true);
  const [baseEmoOn, setBaseEmoOn] = useS1(true);
  const [baseEmo, setBaseEmo] = useS1("grim, brooding");
  const [outfitsOn, setOutfitsOn] = useS1(true);
  const [outfitList, setOutfitList] = useS1([
    { id: 1, name: "парадный доспех", complex: true },
    { id: 2, name: "дорожный плащ", complex: false },
  ]);
  const [outfitArchive, setOutfitArchive] = useS1([{ id: 91, name: "зимняя шуба", complex: false }]);
  const [showOutfitArch, setShowOutfitArch] = useS1(false);
  const [propsOn, setPropsOn] = useS1(false);
  const [propList, setPropList] = useS1([
    { id: 1, name: "Меч «Атлантида»", shots: 2 },
    { id: 2, name: "Огненная магия", shots: 1 },
  ]);
  const [propArchive, setPropArchive] = useS1([]);
  const [showPropArch, setShowPropArch] = useS1(false);
  const [picker, setPicker] = useS1(false);

  function archiveOutfit(o) { setOutfitArchive((a) => [...a, o]); setOutfitList((l) => l.filter((x) => x.id !== o.id)); }
  function restoreOutfit(o) { setOutfitList((l) => [...l, o]); setOutfitArchive((a) => a.filter((x) => x.id !== o.id)); }
  function archiveProp(p) { setPropArchive((a) => [...a, p]); setPropList((l) => l.filter((x) => x.id !== p.id)); }
  function restoreProp(p) { setPropList((l) => [...l, p]); setPropArchive((a) => a.filter((x) => x.id !== p.id)); }

  const emptyOutfit = outfitsOn && outfitList.some((o) => !o.name.trim());
  const emptyProp = propsOn && propList.some((p) => !p.name.trim());
  const blockers = [];
  if (emptyOutfit) blockers.push("у наряда не заполнено название");
  if (emptyProp) blockers.push("у предмета не заполнено название");
  const canNext = blockers.length === 0;

  // controlled character card — feeds the FACE / BODY prompt layers
  const [card, setCard] = useS1({
    gender: "муж.", age: "около 30", build: "атлетическое, мощное",
    hair: "чёрные, до плеч", eyes: "тёмные", skin: "загорелая, обветренная", role: "наёмник, воин",
  });
  const [marks, setMarks] = useS1("шрам на левой щеке, выцветшая татуировка на левом предплечье");
  function setF(k, v) { setCard((c) => ({ ...c, [k]: v })); }

  // Seed the whole form from the persisted character (degrades to the sample
  // defaults above when there is no backend / no active id).
  React.useEffect(() => {
    if (!ctx.activeCharId) return;
    let alive = true;
    window.api.getCharacter(ctx.activeCharId).then((d) => {
      if (!alive || !d || !d.character) return;
      const c = d.character;
      if (c.card) {
        const card2 = { ...c.card };
        if (card2.gender === "male") card2.gender = "муж.";
        else if (card2.gender === "female") card2.gender = "жен.";
        setCard(card2);
      }
      setMarks(c.marks || "");
      if (c.emotions) {
        setEmoOn(!!c.emotions.enabled);
        const b = c.emotions.base || {};
        setBaseEmoOn(!!b.enabled);
        setBaseEmo(b.value || "");
      }
      if (c.outfits) {
        setOutfitsOn(!!c.outfits.enabled);
        if (Array.isArray(c.outfits.list))
          setOutfitList(c.outfits.list.map((o) => ({ id: o.id, name: o.name, complex: !!o.complex })));
      }
      if (c.props) {
        setPropsOn(!!c.props.enabled);
        if (Array.isArray(c.props.list))
          setPropList(c.props.list.map((p) => ({ id: p.id, name: p.name, shots: p.shots || 1 })));
      }
    }).catch(() => {});
    return () => { alive = false; };
  }, [ctx.activeCharId]);

  // Persist the edited anketa, then advance to the passport step.
  async function saveAndNext() {
    if (!canNext) return;
    if (ctx.activeCharId) {
      try {
        await window.api.saveAnketa(ctx.activeCharId, {
          card,
          marks,
          emotions: { enabled: emoOn, base: { enabled: baseEmoOn, value: baseEmo } },
          outfits: { enabled: outfitsOn, list: outfitList.map((o) => ({ name: o.name, complex: o.complex })) },
          props: { enabled: propsOn, list: propList.map((p) => ({ name: p.name })) },
        });
      } catch (e) { /* offline preview: navigate anyway */ }
    }
    ctx.go("passport");
  }

  const FIELDS = [
    { k: "gender", lbl: "Пол", type: "select", opts: ["муж.", "жен."], req: true, layer: "body" },
    { k: "age", lbl: "Возраст", layer: "face" },
    { k: "build", lbl: "Телосложение", layer: "body" },
    { k: "hair", lbl: "Волосы", layer: "face" },
    { k: "eyes", lbl: "Глаза", layer: "face" },
    { k: "skin", lbl: "Тон кожи", layer: "face" },
    { k: "role", lbl: "Роль / статус", layer: "context" },
  ];

  return (
    <div>
      <div className="eyebrow">Шаг 1 из 6 · Анкета</div>
      <h1 className="pagetitle">Кто такой <span className="accent">{ctx.activeChar}</span>?</h1>
      <p className="kicker">Заполните карточку героя — это «словесный портрет». Чем точнее опишете, тем
        больше герой будет похож на задуманного. Не переживайте за формулировки: позже всё можно поправить.</p>

      <Help title="Что заполнять обязательно, а что нет?">
        <p><b>Обязательно — только пол.</b> Без него нейросеть будет «угадывать монеткой».
          Возраст и остальное — желательно, но не критично.</p>
        <p>Самое ценное поле — <b>«Особые приметы»</b> внизу: шрамы, татуировки, повязка на глазу,
          борода. Именно приметы делают героя узнаваемым.</p>
        <p>Блоки <b>Эмоции, Наряды, Предметы</b> — по желанию. Включайте галочкой только то, что нужно
          вашему герою. Выключенный блок просто пропустится.</p>
      </Help>

      <Panel title="Карточка героя" icon="📋">
        <table className="t">
          <tbody>
            {FIELDS.map((f) => (
              <tr key={f.k}>
                <th style={{ width: 180 }}>{f.lbl}{f.req && <span style={{ color: "var(--red)" }}> *</span>}
                  <span className={"lyr-tag " + f.layer}>{f.layer === "face" ? "→ лицо" : f.layer === "body" ? "→ тело" : "→ осанка/подача"}</span>
                </th>
                <td style={{ padding: 6 }}>
                  {f.type === "select"
                    ? <select className="in" value={card[f.k]} onChange={(e) => setF(f.k, e.target.value)} style={{ border: "none", background: "transparent", boxShadow: "none" }}>{f.opts.map((o) => <option key={o}>{o}</option>)}</select>
                    : <input className="in" value={card[f.k]} onChange={(e) => setF(f.k, e.target.value)} style={{ border: "none", background: "transparent", boxShadow: "none" }} />}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <Field ru="Особые приметы" right={<span className="badge now">важно для сходства</span>} hint={<DoDont yes="шрамы, тату, борода, повязка, протез, родинки" no="одежду, позу, настроение — для них есть отдельные шаги" />}>
          <textarea className="in" rows={2} value={marks} onChange={(e) => setMarks(e.target.value)} />
          <p className="tip" style={{ marginTop: 7 }}><span className="ic">ℹ</span><span>Обязателен только <b>пол</b>. Но именно <b>приметы</b> делают героя узнаваемым — без них он выйдет «средним». Поэтому это самое ценное поле для сходства.</span></p>
        </Field>

        {/* assembled FACE / BODY — shows how the card feeds the prompt layers */}
        <div className="assembled" style={{ marginTop: 16 }}>
          <div className="assembled-h">Что из этого соберётся <span className="muted" style={{ fontWeight: 400 }}>— анкета превращается в слои промта</span></div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div>
              <div className="lyr-row-h"><span className="dot" style={{ background: "var(--red)" }}></span><b>Лицо</b> <span className="mono" style={{ fontSize: 10, color: "var(--ink-3)" }}>FACE</span></div>
              <div className="chiprow" style={{ marginTop: 5 }}>
                <span className="pchip">возраст: {card.age || "—"}</span>
                <span className="pchip">волосы: {card.hair || "—"}</span>
                <span className="pchip">глаза: {card.eyes || "—"}</span>
                <span className="pchip">кожа: {card.skin || "—"}</span>
                <span className="pchip detail">приметы лица: {faceMarks(marks) || "—"}</span>
              </div>
            </div>
            <div>
              <div className="lyr-row-h"><span className="dot" style={{ background: "var(--red)" }}></span><b>Тело</b> <span className="mono" style={{ fontSize: 10, color: "var(--ink-3)" }}>BODY</span></div>
              <div className="chiprow" style={{ marginTop: 5 }}>
                <span className="pchip">пол: {card.gender}</span>
                <span className="pchip">телосложение: {card.build || "—"}</span>
                <span className="pchip detail">приметы тела: {bodyMarks(marks) || "—"}</span>
              </div>
            </div>
            <div>
              <div className="lyr-row-h"><span className="dot" style={{ background: "var(--ink-3)" }}></span><b>Поза / подача</b> <span className="mono" style={{ fontSize: 10, color: "var(--ink-3)" }}>COMPOSITION</span></div>
              <div className="chiprow" style={{ marginTop: 5 }}>
                <span className="pchip frame">подача из роли: {card.role ? card.role + " → manner & bearing" : "— (не задано)"}</span>
              </div>
            </div>
          </div>
          <p className="tip" style={{ marginTop: 11 }}><span className="ic">→</span><span>Возраст/волосы/глаза/кожа собираются в <b>FACE</b>, пол/телосложение — в <b>BODY</b>; на «Паспорте» вы их проверите и <b>заморозите</b> 🔒. <b>Роль/статус</b> не входит во внешность — он подмешивается в слой <b>COMPOSITION</b> на кадрах сцен как «манера держаться» (осанка, подача), поэтому в паспорте его не видно, а в сценах — да. Можно оставить пустым.</span></p>
        </div>
      </Panel>

      {/* base outfit — read only */}
      <Panel title="Базовый наряд" icon="👕" className="grey" badge={<span className="badge ro">только чтение</span>}>
        <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>Главный, «привычный» костюм героя. Его вы зададите на шаге паспорта (он появится на плечах в первом кадре). Здесь — просто для справки.</p>
        <PromptField value="dark fur-trimmed leather tunic, wide leather belt" readOnly rows={1} />
      </Panel>

      {/* emotions */}
      <Panel title="Эмоции" icon="😐" badge={<span className="badge opt">по желанию</span>} actions={<Toggle on={emoOn} onToggle={setEmoOn} />}>
        <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>Если герой часто меняет настроение — соберём 3 эталона мимики: спокойствие, злость, улыбка.</p>
        <div style={{ opacity: emoOn ? 1 : 0.45, pointerEvents: emoOn ? "auto" : "none" }}>
          <table className="t">
            <thead><tr><th>Эмоция</th><th>Что это</th><th style={{ width: 150 }}>Референс</th></tr></thead>
            <tbody>
              <tr><td className="mono">neutral</td><td>спокойное лицо</td><td><span className="badge done">✓ есть</span></td></tr>
              <tr><td className="mono">angry, furious</td><td>злость, ярость</td><td className="muted">— нет</td></tr>
              <tr><td className="mono">smiling warmly</td><td>тёплая улыбка</td><td className="muted">— нет</td></tr>
            </tbody>
          </table>
        </div>
      </Panel>

      {/* base emotion */}
      <Panel title="Эмоция по умолчанию" icon="🎭" badge={<span className="badge opt">по желанию</span>} actions={<Toggle on={baseEmoOn} onToggle={setBaseEmoOn} />}>
        <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>«Обычное» выражение лица героя — каким он будет на большинстве кадров (кроме паспорта, там лицо всегда спокойное).</p>
        <div style={{ opacity: baseEmoOn ? 1 : 0.45, pointerEvents: baseEmoOn ? "auto" : "none" }}>
          <Field ru="Настроение героя" en="EXPRESSION" hint={<div className="tip"><span className="ic">💡</span><span>Короткое слово или фраза по-английски, как в примерах. Не уверены — нажмите «Готовые эмоции».</span></div>}>
            <div className="btnrow" style={{ flexWrap: "nowrap" }}>
              <div style={{ flex: 1 }}>
                <PromptField value={baseEmo} onChange={setBaseEmo} rows={1} layer="Эмоция" />
              </div>
              <button className="btn sm" onClick={() => setPicker(true)} style={{ whiteSpace: "nowrap" }}>Готовые эмоции…</button>
            </div>
          </Field>
        </div>
      </Panel>

      {/* outfits */}
      <Panel title="Дополнительные наряды" icon="🧥" badge={<span className="badge opt">по желанию</span>} actions={<Toggle on={outfitsOn} onToggle={setOutfitsOn} />}>
        <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>Если герой переодевается (доспех, плащ, парадный костюм) — перечислите наряды здесь. Снимать их будете на шаге «Наряды». Базовый костюм уже есть выше, его добавлять не нужно.</p>
        <div style={{ opacity: outfitsOn ? 1 : 0.45, pointerEvents: outfitsOn ? "auto" : "none" }}>
          {outfitList.map((o, i) => (
            <div className="outfit-row" key={o.id}>
              <input className={"in" + (!o.name.trim() ? " err" : "")} value={o.name} placeholder="название наряда, напр. «парадный доспех»"
                onChange={(e) => setOutfitList(outfitList.map((x) => x.id === o.id ? { ...x, name: e.target.value } : x))} />
              <label className={"chk sm-chk" + (o.complex ? " on" : "")} title="Костюм с мелкими деталями (гравировка, узор) — добавит кадр в профиль и макро-планы"
                onClick={(e) => { e.preventDefault(); setOutfitList(outfitList.map((x) => x.id === o.id ? { ...x, complex: !x.complex } : x)); }}>
                <span className="bx">{Ico.check}</span><span style={{ fontSize: 12.5, whiteSpace: "nowrap" }}>сложный</span>
              </label>
              <button className="btn ghost sm archive-btn" title="Убрать в архив — можно вернуть"
                onClick={() => archiveOutfit(o)}>🗄 в архив</button>
            </div>
          ))}
          <div className="addrow" style={{ padding: 11, border: "1.5px dashed var(--line-2)", borderRadius: 8, marginTop: 4 }}
            onClick={() => setOutfitList([...outfitList, { id: Date.now(), name: "", complex: false }])}>+ добавить наряд</div>
          <p className="tip" style={{ marginTop: 10 }}><span className="ic">💡</span><span><b>«Сложный»</b> — это галочка для костюмов с мелкими деталями (гравировка, пряжки, узор): на шаге нарядов она добавит ещё кадр в профиль и крупные планы деталей. Для простой одежды не нужна.</span></p>

          {outfitArchive.length > 0 && (
            <div className="archbox">
              <button className="archbox-h" onClick={() => setShowOutfitArch(!showOutfitArch)}>
                <span>🗄 Архив нарядов</span>
                <span className="badge ro">{outfitArchive.length}</span>
                <span className="spacer" style={{ flex: 1 }}></span>
                <span className="muted" style={{ fontSize: 12 }}>{showOutfitArch ? "скрыть" : "показать"}</span>
                <span className="tw" style={{ transform: showOutfitArch ? "rotate(180deg)" : "none" }}>▾</span>
              </button>
              {showOutfitArch && (
                <div className="archbox-body">
                  <p className="muted" style={{ fontSize: 12, margin: "0 0 8px" }}>Убранные наряды не пропадают — верните любой обратно в список.</p>
                  {outfitArchive.map((o) => (
                    <div className="arch-row" key={o.id}>
                      <span className="arch-nm">{o.name || "без названия"}{o.complex && <span className="badge opt" style={{ marginLeft: 8, fontSize: 9 }}>сложный</span>}</span>
                      <button className="btn ghost sm" onClick={() => restoreOutfit(o)}>↩ Вернуть</button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </Panel>

      {/* props */}
      <Panel title="Предметы и магия" icon="⚔️" badge={<span className="badge opt">по желанию</span>} actions={<Toggle on={propsOn} onToggle={setPropsOn} />}>
        <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>Фирменное оружие, артефакты, магические эффекты — то, что должно выглядеть одинаково в каждой сцене. Снимать их будете на шаге «Предметы».</p>
        <div style={{ opacity: propsOn ? 1 : 0.45, pointerEvents: propsOn ? "auto" : "none" }}>
          {propList.map((p) => (
            <div className="outfit-row" key={p.id}>
              <input className={"in" + (!p.name.trim() ? " err" : "")} value={p.name} placeholder="название, напр. «Меч „Атлантида“» или «огненная магия»"
                onChange={(e) => setPropList(propList.map((x) => x.id === p.id ? { ...x, name: e.target.value } : x))} />
              <div className="shots-pick" title="Сколько кадров снять для этого предмета (1–3)">
                <span className="muted" style={{ fontSize: 12 }}>кадров:</span>
                {[1, 2, 3].map((n) => (
                  <button key={n} className={"shot-n" + (p.shots === n ? " on" : "")}
                    onClick={() => setPropList(propList.map((x) => x.id === p.id ? { ...x, shots: n } : x))}>{n}</button>
                ))}
              </div>
              <button className="btn ghost sm archive-btn" title="Убрать в архив — можно вернуть"
                onClick={() => archiveProp(p)}>🗄 в архив</button>
            </div>
          ))}
          <div className="addrow" style={{ padding: 11, border: "1.5px dashed var(--line-2)", borderRadius: 8, marginTop: 4 }}
            onClick={() => setPropList([...propList, { id: Date.now(), name: "", shots: 1 }])}>+ добавить предмет</div>

          {propArchive.length > 0 && (
            <div className="archbox">
              <button className="archbox-h" onClick={() => setShowPropArch(!showPropArch)}>
                <span>🗄 Архив предметов</span>
                <span className="badge ro">{propArchive.length}</span>
                <span className="spacer" style={{ flex: 1 }}></span>
                <span className="muted" style={{ fontSize: 12 }}>{showPropArch ? "скрыть" : "показать"}</span>
                <span className="tw" style={{ transform: showPropArch ? "rotate(180deg)" : "none" }}>▾</span>
              </button>
              {showPropArch && (
                <div className="archbox-body">
                  <p className="muted" style={{ fontSize: 12, margin: "0 0 8px" }}>Убранные предметы не пропадают — верните любой обратно.</p>
                  {propArchive.map((p) => (
                    <div className="arch-row" key={p.id}>
                      <span className="arch-nm">{p.name || "без названия"}<span className="badge opt" style={{ marginLeft: 8, fontSize: 9 }}>{p.shots} кадр.</span></span>
                      <button className="btn ghost sm" onClick={() => restoreProp(p)}>↩ Вернуть</button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </Panel>

      <div style={{ marginTop: 24 }}>
        {!canNext && (
          <div className="notice red" style={{ marginBottom: 14 }}>
            <span className="ic">✏️</span>
            <span className="tx"><b>Заполните названия, чтобы продолжить:</b> {blockers.join("; ")}. Пустые строки либо назовите, либо уберите в архив.</span>
          </div>
        )}
        <div className="btnrow split">
          <button className="btn ghost" onClick={() => ctx.go("start")}>← Назад</button>
          <button className={"btn " + (canNext ? "go" : "disabled")} disabled={!canNext}
            onClick={saveAndNext} title={canNext ? "" : "Сначала заполните названия"}>
            {canNext ? "Дальше: паспорт героя →" : "🔒 Заполните названия"}
          </button>
        </div>
      </div>

      {picker && <PresetPicker onPick={setBaseEmo} onClose={() => setPicker(false)} />}
    </div>
  );
}

window.ScreenStart = ScreenStart;
window.ScreenData = ScreenData;
