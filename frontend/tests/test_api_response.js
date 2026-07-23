const assert = require("node:assert/strict");
const { readApiJson } = require("../api_response.js");


async function testRejectsHtmlWithActionableRestartMessage() {
    const response = {
        status: 404,
        headers: { get: () => "text/html; charset=utf-8" },
        json: async () => { throw new Error("should not parse HTML as JSON"); },
    };

    await assert.rejects(
        () => readApiJson(response, "学习计划"),
        /服务版本未更新.*重启/,
    );
}


async function testReturnsJsonPayload() {
    const payload = { plan: { theme: "日常交流" } };
    const response = {
        status: 200,
        headers: { get: () => "application/json" },
        json: async () => payload,
    };

    assert.deepEqual(await readApiJson(response, "学习计划"), payload);
}


Promise.all([
    testRejectsHtmlWithActionableRestartMessage(),
    testReturnsJsonPayload(),
]).then(() => {
    console.log("api_response tests passed");
});
