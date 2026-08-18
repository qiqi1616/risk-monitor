/**
 * 天气看板 API 配置文件（模板）
 * 
 * 使用说明：
 *   1. 复制本文件，重命名为 config.js
 *   2. 填入你的和风天气 API Key
 *   3. 将 config.js 放在与 index.html 同级目录下
 *   4. 用浏览器打开 index.html 即可使用
 * 
 * 安全提醒：
 *   - config.js 包含 API Key，属于敏感文件
 *   - 严禁将 config.js 提交到代码仓库
 *   - config.js 已在 .gitignore 中排除
 * 
 * 和风天气 API Key 申请地址：https://console.qweather.com/
 */

window.__WEATHER_CONFIG__ = {
    // 和风天气 API Key（必填）
    // 需要订阅：实时天气、3天预报、天气预警
    API_KEY: '在此填入你的和风天气API Key',

    // 和风天气 API 域名（一般无需修改）
    // 免费订阅用 devapi.qweather.com
    // 付费订阅用 xxx.re.qweatherapi.com（xxx为你的子域名）
    API_DOMAIN: 'devapi.qweather.com',

    // 预警 API 配置（可选，不填则使用主 API_KEY）
    // WARNING_API_KEY: '',
    // WARNING_API_DOMAIN: '',

    // 备用预警 API 配置（可选）
    // WARNING_API_KEY_FALLBACK: '',
    // WARNING_API_DOMAIN_FALLBACK: 'devapi.qweather.com',
};
