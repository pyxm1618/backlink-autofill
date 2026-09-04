# backlink-autofill

半自动高质量外链提交 Chrome 扩展：**明确选择当前项目 → 从项目审核过的标准资料取值 → AI 读取当前网站/表单并按需微调 → 自动填写 → 人工检查并点击最终 Submit。**

## MVP 当前能力

- 强制显式选择当前项目；未选择项目时禁止运行。
- 每个项目独立保存：主关键词、次关键词、Title、Tagline、多长度 Description、Tags、Categories、事实清单、禁止声称、联系信息与素材。
- AI 优先使用审核过的标准资料，只能因字段长度/格式/站点语境做必要改写，不允许新增未经审核的产品事实。
- 可读取项目配置的 Google Sheet 外链列表；Quick I Ching 默认指向现有 BacklinkOS 主库的 `严格免费外链` 执行页，而不是发现候选池。
- 会保留 Sheet 中的提交条件/备注，例如换链、Top 3、upvote 门槛等，供执行前判断。
- 可直接对当前标签页执行 Fill，也可从 Sheet 选择目标后 Open & fill。
- 允许尝试浏览器现有登录态下的普通 Google/GitHub OAuth。
- CAPTCHA、滑块、Cloudflare、2FA、手机确认等安全验证交给人工处理。
- Agent 必须停在最终 Submit / Publish / Launch 之前。

## 安装

CI 会生成名为 `backlink-autofill-chrome` 的构建产物。解压后在 Chrome `chrome://extensions` 开启开发者模式并选择 **Load unpacked**。

本地构建：

```bash
cd extension
npm install
npm test
npm run typecheck
npm run build
```

构建目录：`extension/.output/chrome-mv3`。

## 建议使用方式

使用一个专门的“外链工作” Chrome Profile，并提前登录 Google 和常用网站。安装扩展后：

1. 明确选择当前项目。
2. 检查/编辑该项目的标准提交资料。
3. 配置 LLM Base URL、Model、API Key。
4. `Load from Sheet` 读取外链目标，或直接打开任意提交页后点 `Fill current tab`。
5. 登录正常 OAuth 可让 Agent 尝试；安全验证由人工完成。
6. AI 填完后人工检查并点击最终 Submit。

> 私有 Google Sheet 的 MVP 读取方式依赖该 Chrome Profile 已登录且有 Sheet 权限。此路径还需要在真实 Chrome 中做端到端验证；即使 Sheet 读取失败，`Fill current tab` 仍可独立使用。

## Upstream

Browser execution is based on `subodhkc/AI-Directory-Autofill-Chrome-Extension` (MIT License) and Alibaba Page Agent. The upstream MIT license is retained in this repository.
