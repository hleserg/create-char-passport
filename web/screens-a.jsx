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
function ScreenStart({ ctx }) {
  const [styleDone, setStyleDone] = useS1(true);
  const [text, setText] = useS1("");
  const [extracted, setExtracted] = useS1(false);

  const found = ["Герон", "Тайра", "Луций"];

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
      <Panel title="Стиль рисунка" icon="🎨" badge={styleDone ? <span className="badge lock">🔒 закреплён</span> : <span className="badge now">сначала это</span>}>
        <p className="muted" style={{ marginTop: 0, fontSize: 13.5 }}>
          Загрузите 5 примеров картинок в той манере, в которой хотите рисовать историю
          (комикс, акварель, нуар…). Нейросеть посмотрит на них и опишет стиль словами — дальше
          все картинки будут в этой манере.
        </p>
        <div className="pv-grid" style={{ gridTemplateColumns: "repeat(5,1fr)", marginBottom: 14 }}>
          {[0, 1, 2, 3, 4].map((i) => (
            <div className="pv ready" key={i} style={{ minHeight: 92 }}>
              <Figure kind="item" size={34} />
              <span className="pv-sub">пример {i + 1}</span>
            </div>
          ))}
        </div>
        <Field ru="Описание стиля" en="STYLE" hint={<DoDont yes="манеру рисунка, технику, свет, палитру" no="конкретного героя, его лицо, одежду или сцену" />}>
          <PromptField value="graphic novel, bold ink linework, muted watercolour wash, dramatic chiaroscuro lighting, grainy paper texture" readOnly rows={2} />
        </Field>
        <div className="btnrow" style={{ marginTop: 12 }}>
          <span className="stamp lock">🔒 стиль закреплён</span>
          <span className="spacer" style={{ flex: 1 }}></span>
          <button className="btn ghost sm" onClick={() => setStyleDone(false)}>Изменить стиль</button>
        </div>
      </Panel>

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
          <AIButton onClick={() => setExtracted(true)}>Найти героев в тексте</AIButton>
        </div>

        {extracted && (
          <div className="panel soft" style={{ marginTop: 16, marginBottom: 0 }}>
            <div className="field-lbl"><span className="ru">Нашли героев</span></div>
            <div className="btnrow">
              {found.map((n) => (
                <button className="btn sm" key={n} onClick={() => { ctx.setActiveChar(n); ctx.go("data"); }}>
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
            {SAMPLE_CHARS.map((c) => (
              <tr key={c.id}>
                <td style={{ fontWeight: 700 }}>{c.name}</td>
                <td>{c.status === "готов" ? <span className="badge done">✓ готов</span> : <span className="badge now">{c.status}</span>}</td>
                <td>
                  <div className="btnrow" style={{ justifyContent: "flex-end", gap: 8 }}>
                    {c.status === "готов" && (
                      <button className="btn ghost sm" title="Скачать ZIP-архив героя (кадры + промты)" onClick={() => window.downloadHeroArchive && window.downloadHeroArchive(c.name)}>⬇ Скачать</button>
                    )}
                    <button className="btn ghost sm" onClick={() => { ctx.setActiveChar(c.name); ctx.go(c.step || "data"); }}>Открыть →</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
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
            onClick={() => canNext && ctx.go("passport")} title={canNext ? "" : "Сначала заполните названия"}>
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
