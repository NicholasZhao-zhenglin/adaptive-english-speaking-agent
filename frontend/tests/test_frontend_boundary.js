const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");


const frontendDir = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(frontendDir, "index.html"), "utf8");
const script = fs.readFileSync(path.join(frontendDir, "script.js"), "utf8");


assert.match(html, /自适应英语口语 Agent/);
assert.doesNotMatch(html, /新点子记录|日记记录|待办清单|求职助手/);
assert.match(script, /\/api\/english\/dashboard/);
assert.doesNotMatch(script, /\/api\/(idea|diary|todo|job)\//);

console.log("frontend boundary tests passed");
