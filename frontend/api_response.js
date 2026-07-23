(function exposeApiResponseHelper(root, factory) {
    const api = factory();
    if (typeof module === "object" && module.exports) {
        module.exports = api;
    }
    root.readApiJson = api.readApiJson;
})(typeof globalThis !== "undefined" ? globalThis : this, function createApiResponseHelper() {
    async function readApiJson(response, context = "请求") {
        const contentType = response.headers?.get?.("content-type") || "";
        if (!contentType.toLowerCase().includes("application/json")) {
            if (response.status === 404) {
                throw new Error(`${context}接口不存在，服务版本未更新，请重启本地助手`);
            }
            throw new Error(`${context}返回了非 JSON 响应（HTTP ${response.status}）`);
        }
        try {
            return await response.json();
        } catch (_error) {
            throw new Error(`${context}返回了无法解析的数据`);
        }
    }

    return { readApiJson };
});
