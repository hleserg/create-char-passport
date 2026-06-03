/* =========================================================
   Hero archive builder — store-only ZIP, generated in-browser.
   Plain JS (no JSX). Exposes window.downloadHeroArchive(hero) and
   window.heroArchiveManifest(hero) for the preview tree.
   ========================================================= */
(function () {
  // ---- CRC32 ----
  var T = (function () {
    var t = [], c, n, k;
    for (n = 0; n < 256; n++) { c = n; for (k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; }
    return t;
  })();
  function crc32(buf) { var c = 0xFFFFFFFF, i; for (i = 0; i < buf.length; i++) c = T[(c ^ buf[i]) & 0xFF] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; }
  function bytes(s) { return new TextEncoder().encode(s); }

  function u16(n) { return [n & 255, (n >> 8) & 255]; }
  function u32(n) { n >>>= 0; return [n & 255, (n >> 8) & 255, (n >> 16) & 255, (n >> 24) & 255]; }

  // ---- store-only zip ----
  function makeZip(files) {
    var chunks = [], central = [], offset = 0;
    files.forEach(function (f) {
      var nm = bytes(f.name), data = typeof f.bytes === "string" ? bytes(f.bytes) : f.bytes, crc = crc32(data);
      var lh = [].concat(u32(0x04034b50), u16(20), u16(0x0800), u16(0), u16(0), u16(0),
        u32(crc), u32(data.length), u32(data.length), u16(nm.length), u16(0));
      var lhb = new Uint8Array(lh);
      chunks.push(lhb, nm, data);
      var cd = [].concat(u32(0x02014b50), u16(20), u16(20), u16(0x0800), u16(0), u16(0), u16(0),
        u32(crc), u32(data.length), u32(data.length), u16(nm.length), u16(0), u16(0), u16(0), u16(0),
        u32(0), u32(offset));
      central.push({ rec: new Uint8Array(cd), name: nm });
      offset += lhb.length + nm.length + data.length;
    });
    var cstart = offset, csize = 0;
    central.forEach(function (c) { chunks.push(c.rec, c.name); csize += c.rec.length + c.name.length; });
    chunks.push(new Uint8Array([].concat(u32(0x06054b50), u16(0), u16(0),
      u16(central.length), u16(central.length), u32(csize), u32(cstart), u16(0))));
    var total = chunks.reduce(function (a, c) { return a + c.length; }, 0), out = new Uint8Array(total), p = 0;
    chunks.forEach(function (c) { out.set(c, p); p += c.length; });
    return out;
  }

  // ---- demo data model (in real app this comes from the saved session) ----
  function model(hero) {
    var style = "graphic novel, bold ink linework, muted watercolour wash, dramatic chiaroscuro lighting, grainy paper texture";
    var face = "coarse face, broad nose, full lips, deep-set dark eyes, short rough dark hair, weathered tanned skin";
    var body = "stocky, powerfully built, broad shoulders, faded tattoo on left forearm";
    var baseOutfit = "dark fur-trimmed leather tunic, wide leather belt";
    var grey = "plain neutral grey background, soft even lighting, neutral expression, no frame";

    var approved = [
      { sect: "passport", view: "face_front-portrait", gen: 2, layers: { style: style, face: face, outfit: baseOutfit, composition: "front facing portrait, head and shoulders, " + grey } },
      { sect: "passport", view: "body_front-full", gen: 1, layers: { style: style, face: face, body: body, outfit: baseOutfit, composition: "full-length, head-to-toe, standing straight, " + grey } },
      { sect: "passport", view: "profile-portrait", gen: 3, layers: { style: style, face: face, composition: "strict side profile, 90 degrees, head and shoulders, " + grey } },
      { sect: "passport", view: "back-full", gen: 1, layers: { style: style, body: body, outfit: baseOutfit, composition: "full-length back view, head-to-toe, " + grey } },
      { sect: "passport", view: "threeq-full", gen: 2, layers: { style: style, face: face, body: body, outfit: baseOutfit, composition: "full-length three-quarter angle, " + grey } },
      { sect: "emotions", view: "neutral", gen: 1, layers: { style: style, face: face, expression: "neutral", composition: "front portrait, head and shoulders, " + grey } },
      { sect: "outfit_parade", view: "front-full", gen: 1, layers: { style: style, face: face, body: body, outfit: "ornate ceremonial plate armor, engraved pauldrons, crimson cloak", composition: "full-length, head-to-toe, " + grey } },
      { sect: "outfit_parade", view: "back-full", gen: 2, layers: { style: style, body: body, outfit: "ornate ceremonial plate armor, crimson cloak", composition: "full-length back view, " + grey } },
      { sect: "prop_sword", view: "overview", gen: 1, layers: { style: style, item: "ancient bronze longsword, ornate hilt, runic engravings", composition: "product shot, centered, plain background, no character" } },
    ];
    var rejected = [
      { sect: "passport", view: "profile-portrait", gen: 1, reason: "лицо развернулось к камере (не строгий профиль)", layers: { style: style, face: face, composition: "side profile attempt, " + grey } },
      { sect: "passport", view: "profile-portrait", gen: 2, reason: "поза 3/4 вместо профиля", layers: { style: style, face: face, composition: "profile attempt, " + grey } },
      { sect: "passport", view: "body_front-full", gen: 1, reason: "ноги обрезаны кадром", layers: { style: style, body: body, outfit: baseOutfit, composition: "full body, " + grey } },
      { sect: "outfit_parade", view: "front-full", gen: 1, reason: "плащ перекрыл лицо", layers: { style: style, outfit: "ceremonial plate armor, crimson cloak", composition: "full-length, " + grey } },
    ];
    return { hero: hero, created: new Date().toISOString().slice(0, 10), style: style,
      identity: { face: face, body: body, base_outfit: baseOutfit }, approved: approved, rejected: rejected };
  }

  function pad(n) { return (n < 10 ? "0" : "") + n; }

  function genTxt(rec, kind) {
    var L = rec.layers, lines = [];
    lines.push("# " + (kind === "rejected" ? "ОТКЛОНЁННАЯ" : "ОДОБРЕННАЯ") + " генерация");
    lines.push("section : " + rec.sect);
    lines.push("view    : " + rec.view);
    lines.push("gen #   : " + rec.gen);
    if (rec.reason) lines.push("причина : " + rec.reason);
    lines.push("");
    lines.push("# Промт по слоям (то, что ушло в нейросеть):");
    Object.keys(L).forEach(function (k) { lines.push(k.toUpperCase().padEnd ? k.toUpperCase() : k.toUpperCase()); lines.push("  " + L[k]); });
    lines.push("");
    lines.push("[ В реальном приложении здесь лежит PNG-кадр. В макете — этот текст-заглушка с промтом. ]");
    return lines.join("\n");
  }

  window.heroArchiveManifest = model;

  window.downloadHeroArchive = function (hero) {
    hero = hero || "Герой";
    var m = model(hero);
    var files = [];

    // master manifest with ALL prompts
    files.push({ name: hero + "/passport.json", bytes: JSON.stringify(m, null, 2) });

    // README
    files.push({ name: hero + "/README.txt", bytes:
      "ПАСПОРТ ПЕРСОНАЖА — " + hero + "\n" +
      "Дата: " + m.created + "\n\n" +
      "Структура архива:\n" +
      "  passport.json     — все слои и промты по каждой генерации (главный файл)\n" +
      "  approved/         — одобренные кадры (имя: NN_секция_ракурс_genN)\n" +
      "  rejected/         — отклонённые кадры в отдельной папке, помечены\n" +
      "                      названием и номером генерации (rej_NN_..._genN)\n\n" +
      "В реальном приложении в approved/ и rejected/ лежат PNG-файлы.\n" +
      "В этом макете вместо картинок — текстовые заглушки с промтом каждого кадра.\n"
    });

    // approved — structured
    m.approved.forEach(function (r, i) {
      files.push({ name: hero + "/approved/" + pad(i + 1) + "_" + r.sect + "_" + r.view + "_gen" + r.gen + ".txt", bytes: genTxt(r, "approved") });
    });
    // rejected — separate folder, marked with name + gen number
    m.rejected.forEach(function (r, i) {
      files.push({ name: hero + "/rejected/rej_" + pad(i + 1) + "_" + r.sect + "_" + r.view + "_gen" + r.gen + ".txt", bytes: genTxt(r, "rejected") });
    });

    var blob = new Blob([makeZip(files)], { type: "application/zip" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url; a.download = hero + "_паспорт.zip";
    document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 1500);
    return { approved: m.approved.length, rejected: m.rejected.length };
  };
})();
