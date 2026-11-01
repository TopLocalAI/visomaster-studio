// End-to-end UI flow against a real backend and real models (synthetic media only).
// Usage: node tests/ui-flow.mjs <playwright module dir> <output dir>
// Requires the Vite dev server on :1420 (pnpm dev) and an installed base model set.
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { webkit } = require(path.join(process.argv[2], "playwright"));
const OUT = path.resolve(process.argv[3]);
const DESKTOP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const ROOT = path.dirname(DESKTOP);
const MODELS = process.env.VISOMASTER_TEST_MODELS ?? path.join(os.homedir(), "Library/Application Support/VisoMasterStudio/models");
const PORTRAIT = path.join(ROOT, "design/assets/synthetic-portrait.png");
const REFERENCE = path.join(ROOT, "benchmarks/studio-complete-2026-10-06/second-reference.png");
const VIDEO = path.join(ROOT, "benchmarks/studio-regression-2026-10-06/eight-seconds.mp4");

fs.mkdirSync(OUT, { recursive: true });
const result = { started: new Date().toISOString(), engine: "webkit (Playwright)", steps: [] };
const step = (name, data = {}) => {
  result.steps.push({ name, ...data });
  console.log("✓", name, Object.keys(data).length ? JSON.stringify(data) : "");
};

function startBackend(home, modelDir, token) {
  fs.mkdirSync(home, { recursive: true });
  fs.writeFileSync(path.join(home, "settings.json"), JSON.stringify({ model_dir: modelDir, output_dir: path.join(home, "exports") }));
  const proc = spawn(path.join(DESKTOP, ".venv-studio/bin/python"), ["studio_backend.py"], {
    cwd: DESKTOP,
    env: { ...process.env, VISOMASTER_STUDIO_HOME: home, VISOMASTER_BACKEND_TOKEN: token },
    stdio: ["pipe", "pipe", fs.openSync(path.join(home, "backend.log"), "w")],
  });
  return new Promise((resolve, reject) => {
    proc.stdout.on("data", (d) => {
      const line = d.toString().split("\n").find((l) => l.startsWith("VISOMASTER_BACKEND "));
      if (line) resolve({ proc, port: JSON.parse(line.slice(19)).port });
    });
    proc.on("exit", (code) => reject(new Error(`backend exited ${code}`)));
  });
}

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "studio-ui-"));
const token = "ui-test-token";
const main = await startBackend(path.join(tmp, "main"), MODELS, token);
const empty = await startBackend(path.join(tmp, "empty"), path.join(tmp, "no-models"), token);
const browser = await webkit.launch();
const context = await browser.newContext({ viewport: { width: 1360, height: 860 }, deviceScaleFactor: 2 });
const page = await context.newPage();
const consoleErrors = [];
page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); if (process.env.DEBUG_UI) console.log("[page]", m.type(), m.text()); });
page.on("pageerror", (e) => consoleErrors.push(String(e)));
if (process.env.DEBUG_UI) page.on("websocket", (ws) => ws.on("framesent", (f) => { const m = JSON.parse(f.payload); console.log("→", m.method, String(JSON.stringify(m.params)).slice(0, 140)); }));
const shot = (name) => page.screenshot({ path: path.join(OUT, `${name}.png`) });
const idle = async () => {
  await page.waitForFunction(() => !document.querySelector(".spin-overlay"), null, { timeout: 120000 });
};

try {
  // Missing models: onboarding state with size, no automatic download.
  await page.goto(`http://localhost:1420/?port=${empty.port}&token=${token}`);
  await page.getByRole("heading", { name: "下载基础模型" }).waitFor();
  await shot("01-models-missing");
  step("missing base models shows download prompt", { text: await page.locator(".empty p").first().innerText() });

  // Unreachable backend: explicit error with retry.
  await page.goto(`http://localhost:1420/?port=1&token=${token}`);
  await page.getByRole("heading", { name: "无法连接处理组件" }).waitFor();
  await shot("02-backend-unreachable");
  step("unreachable backend shows error");

  await page.goto(`http://localhost:1420/?port=${main.port}&token=${token}`);
  await page.getByText("添加图片或视频").waitFor({ timeout: 60000 });
  await shot("03-empty");
  step("engine ready, empty workspace");

  let t = Date.now();
  await page.evaluate((p) => window.__studio.addMedia([p]), PORTRAIT);
  await page.getByText("添加参考脸后开始替换").waitFor({ timeout: 60000 });
  await page.locator("img.frame").waitFor();
  await idle();
  await shot("04-image-no-reference");
  step("image added, face detected", { ms: Date.now() - t, targets: await page.locator(".mapping").count() });

  t = Date.now();
  await page.evaluate((p) => window.__studio.addSources([p]), REFERENCE);
  await page.getByText("1 个人脸 · 已替换", { exact: false }).waitFor({ timeout: 60000 });
  await idle();
  await shot("05-image-swapped");
  step("reference added and auto-assigned, preview rendered", { ms: Date.now() - t, status: await page.locator(".viewbar .status").innerText() });

  await page.getByRole("switch", { name: "画质修复" }).click();
  await page.waitForTimeout(300);
  await idle();
  await shot("06-restorer-on");
  step("face restorer enabled from inspector", { modifiedRows: await page.locator(".row.mod").count() });

  await page.getByRole("button", { name: "对比" }).click();
  await page.waitForTimeout(200);
  await idle();
  await shot("07-compare-view");
  step("compare view rendered");
  await page.getByRole("button", { name: "结果" }).click();

  await page.getByRole("button", { name: "高级设置" }).click();
  await page.locator(".group-head", { hasText: "遮罩" }).click();
  await shot("08a-advanced");
  await page.getByPlaceholder(/搜索 \d+ 项参数/).fill("xseg");
  await shot("08-search");
  step("advanced settings: groups and search", { hits: await page.locator(".hit").count() });
  await page.getByRole("button", { name: "返回" }).click();

  // Export while compare had been used: output must be the plain result at full size.
  t = Date.now();
  await page.getByRole("button", { name: "导出", exact: true }).click();
  await page.getByText("已导出", { exact: false }).waitFor({ timeout: 120000 });
  await shot("09-image-exported");
  const images = fs.readdirSync(path.join(tmp, "main/exports")).filter((f) => f.endsWith(".png"));
  step("image exported", { ms: Date.now() - t, files: images });

  // Bad reference input: visible error, workspace unchanged.
  await page.evaluate((p) => window.__studio.addSources([p]), path.join(DESKTOP, "STUDIO.md"));
  await page.getByText("请使用图片", { exact: false }).waitFor();
  await shot("10-invalid-reference");
  step("invalid reference reports error");

  // Video: transport, range and export with progress.
  await page.evaluate((p) => window.__studio.addMedia([p]), VIDEO);
  await page.locator(".transport").waitFor({ timeout: 60000 });
  await page.getByText("已替换", { exact: false }).waitFor({ timeout: 60000 });
  await page.locator("img.frame").waitFor({ timeout: 60000 });
  await idle();
  await shot("11-video");
  step("video added: timeline visible, face matched");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("i");
  for (let i = 0; i < 9; i++) await page.keyboard.press("ArrowRight");
  await page.keyboard.press("o");
  await idle();
  await shot("12-video-range");
  step("range set with I/O keys", { range: await page.locator(".range-chip").innerText() });
  t = Date.now();
  await page.getByRole("button", { name: "导出", exact: true }).click();
  await page.waitForTimeout(400);
  await shot("13a-after-export-click");
  await page.getByRole("button", { name: "任务" }).click();
  await page.locator(".popover").getByText("导出 eight-seconds.mp4").waitFor();
  await shot("13-video-exporting");
  await page.locator(".popover .job").filter({ hasText: "eight-seconds" }).getByRole("button", { name: "显示" }).waitFor({ timeout: 300000 });
  await shot("14-video-exported");
  const videos = fs.readdirSync(path.join(tmp, "main/exports")).filter((f) => f.endsWith(".mp4"));
  step("video range exported", { ms: Date.now() - t, files: videos });
  await page.keyboard.press("Escape");

  // Markers, segments and a two-segment export.
  await page.keyboard.press("Home");
  for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("m");
  await page.locator(".track .marker").first().waitFor();
  await page.keyboard.press("i");
  for (let i = 0; i < 2; i++) await page.keyboard.press("ArrowRight");
  await page.keyboard.press("o");
  await page.getByRole("button", { name: "加为导出分段" }).click();
  for (let i = 0; i < 8; i++) await page.keyboard.press("ArrowRight");
  await page.keyboard.press("i");
  for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowRight");
  await page.keyboard.press("o");
  await page.getByRole("button", { name: "加为导出分段" }).click();
  await idle();
  await shot("17-markers-segments");
  step("marker and two segments", { markers: await page.locator(".track .marker").count(), segments: await page.locator(".seg-chip").count() });
  const mp4s = () => fs.readdirSync(path.join(tmp, "main/exports")).filter((f) => f.endsWith(".mp4") && !f.startsWith("."));
  const before = new Set(mp4s());
  await page.getByRole("button", { name: /导出 2 段/ }).click();
  let segFile = null;
  for (let i = 0; i < 600 && !segFile; i++) {
    await page.waitForTimeout(500);
    segFile = mp4s().find((f) => !before.has(f)) ?? null;
  }
  if (!segFile) throw new Error("two-segment export did not finish");
  await page.waitForFunction(() => !document.body.innerText.includes("导出中"), null, { timeout: 60000 });
  const { execFileSync } = await import("node:child_process");
  const segFrames = Number(execFileSync("ffprobe", ["-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
    "stream=nb_read_frames", "-of", "csv=p=0", path.join(tmp, "main/exports", segFile)]).toString().trim());
  if (segFrames !== 7) throw new Error(`two-segment export has ${segFrames} frames, expected 7`);
  step("two-segment export", { file: segFile, frames: segFrames });

  // Presets through the advanced panel.
  await page.getByRole("button", { name: "高级设置" }).click();
  await page.getByRole("button", { name: "预设" }).click();
  await page.getByRole("menuitem", { name: "保存当前设置为预设…" }).click();
  await page.locator(".prompt-input").fill("柔和修复");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByText("已保存预设", { exact: false }).waitFor();
  await page.getByRole("button", { name: "预设" }).click();
  await shot("18-presets-menu");
  await page.getByRole("menuitem", { name: /柔和修复\s*应用/ }).click();
  step("preset saved and applied");
  await page.getByRole("button", { name: "返回" }).click();

  // Merge reference faces into a saved face.
  await page.getByRole("button", { name: "人脸库" }).click();
  await page.getByRole("menuitem", { name: "把参考脸合并为一个人脸…" }).click();
  await page.getByRole("button", { name: "合并", exact: true }).click();
  await page.locator(".ref.merged").waitFor();
  await shot("19-merged-face");
  step("merged face created", { merged: await page.locator(".ref.merged").count() });

  // Project save and reopen (paths supplied directly; dialogs are native in the app).
  const projectFile = path.join(tmp, "ui-project.json");
  await page.evaluate((p) => window.__studio.client.call("project.save", { path: p }), projectFile);
  await page.getByRole("button", { name: "未命名项目" }).click();
  await page.getByRole("menuitem", { name: "新建项目" }).click();
  await page.getByText("添加图片或视频").waitFor();
  const reopened = await page.evaluate(async (p) => { const st = await window.__studio.client.call("project.open", { path: p }); await window.__studio.applyState(st); return { media: st.media.length, targets: st.targets.length, markers: st.markers.length, segments: st.segments.length }; }, projectFile);
  await page.locator("img.frame").waitFor({ timeout: 60000 });
  await idle();
  await shot("20-project-reopened");
  step("project new / save / reopen", reopened);

  // Live mode, with a video file standing in for a camera (camera access needs a user grant).
  await page.locator(".camera-row").click();
  await page.getByRole("heading", { name: "实时换脸" }).waitFor();
  await page.evaluate((v) => window.__studio.client.call("live.start", { source: v }), VIDEO);
  await page.locator('img.frame[src*="live.mjpg"]').waitFor({ timeout: 60000 });
  await page.getByRole("button", { name: "识别人脸" }).click();
  await page.locator(".mapping").first().waitFor({ timeout: 30000 });
  await page.waitForTimeout(3000);
  await shot("21-live");
  step("live mode with file source", { stats: await page.locator(".live-stats").innerText() });
  await page.getByRole("button", { name: "停止" }).click();
  await page.getByRole("button", { name: "开始" }).first().waitFor();

  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page.getByText("已安装", { exact: false }).first().waitFor();
  await shot("15-settings-models");
  await page.getByRole("button", { name: "运行" }).click();
  await shot("16-settings-run");
  step("settings sheet in main window");
  await page.keyboard.press("Escape");

  // Exported files are copied for inspection; the temporary workspace is removed.
  fs.mkdirSync(path.join(OUT, "exports"), { recursive: true });
  for (const f of fs.readdirSync(path.join(tmp, "main/exports"))) fs.copyFileSync(path.join(tmp, "main/exports", f), path.join(OUT, "exports", f));
  result.ok = true;
} catch (e) {
  result.ok = false;
  result.error = String(e);
  await shot("failure").catch(() => {});
  console.error(e);
} finally {
  result.consoleErrors = consoleErrors;
  fs.writeFileSync(path.join(OUT, "result.json"), JSON.stringify(result, null, 2));
  await browser.close();
  main.proc.stdin.end();
  empty.proc.stdin.end();
  fs.rmSync(tmp, { recursive: true, force: true });
}
process.exit(result.ok ? 0 : 1);
