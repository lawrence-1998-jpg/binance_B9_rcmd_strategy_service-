---
name: control-shipped-but-never-fired
description: 交互控件加了监听不等于它能用——window.X 兜底、init 时序、颜色态在强制配色下失效，三种失效都是静默的；交付前必须逐个触发一遍并观察真实副作用
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-08-04T20:38:02.773Z
---

2026-08-05 Lawrence 投诉："这里加一个 apply 按钮。现在改了之后是不生效的，
要拖动一个别的滑杆才能有效"，并要求"交互设计上要用心，不要太蠢"。

查下去发现混排那三个控件（配额开关 / 数字框 / 置顶开关）**从上线起一次都没生效过**：

```js
el.addEventListener("change", function(){ if (window.runReweight) runReweight(); });
```

整段脚本在 `(function(){ ... })()` 里，`function runReweight(){}` **不会挂到 window**，
`window.runReweight` 恒为 undefined，守卫恒假。用户"拖别的滑杆才有效"完全对得上：
滑杆的回调在同一作用域里直接调，没走这条死链。

**同一次排查里踩到的三种"静默失效"**：

1. **`window.X` 兜底**：跨作用域取函数写成 `if (window.X) X()`，取不到就悄悄什么都不做。
   同作用域直接引用即可；真要兜底也得有断言/日志证明它取到了。
2. **绑定时序**：控件 HTML 一渲染就可点，但 `addEventListener` 在 `init()` 里。
   中间那段窗口（以及 init 在更早处抛异常时）控件是"看得见、点不动"的哑件——
   实测刷新后立刻点确实点不动。**改用 document 级事件委托**，脚本解析时就装好，
   从结构上消灭这个窗口，而不是把时序调准一点。
3. **只用颜色表达状态**：在强制配色 / 高对比度下，浏览器接管表单控件的
   background/border/color——实测连内联 `!important` 都改不动按钮底色，
   而 opacity 照常生效、同样手法在旁边 `<span>` 上完全正常。
   **状态必须同时写进文案**（"应用混排" ↔ "应用混排 ●" + title），颜色只做增强。
   这顺带是实打实的可访问性改善。

**How to apply**：
1. **交付任何交互控件前，逐个触发一遍并观察真实副作用**——不是"我绑了监听"，
   而是"我点了它、请求发出去了、界面变了"。拦 fetch/XHR 看请求体是最硬的证据。
2. 测试要在**最苛刻的时机**做：页面刚刷新就点。那是绑定时序问题唯一会暴露的窗口。
3. **每个可改的东西都要有"我改动了/已应用"的可见回执**。这次补的是按钮文案 +
   一行回显具体配置（"已应用：每 10 条 ≥ 6 条实体 · Top1/Top3 置顶实体"），
   让用户不必靠"去拖个别的滑杆"来确认自己有没有点到。
4. 量样式别用 `getComputedStyle` 的返回对象跨语句读——**它是活对象**，
   你改完 class 再读，读到的是改之后的状态（我因此误判过一次"样式没生效"）。

相关：[[scheduled-job-never-ran]]、[[definition-of-done-user-surface]]、
[[feature-must-cover-all-surfaces]]、[[human-eyeball-test-is-my-floor]]
