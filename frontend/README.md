# Workflow Scheduler Frontend

这是“定时任务调度”的前端源码，使用 Vue 3 + Vite。

## 推荐使用方式

Workflow Scheduler 正常只使用 Flask/Gunicorn 的 `8008` 端口。修改前端源码后，先构建到 `../app/dist`，再访问 `http://127.0.0.1:8008/`。

```powershell
npm.cmd install
npm.cmd run build
```

## 可选开发模式

只有需要 Vue 热更新时才启动 Vite 开发服务。

```powershell
npm.cmd install
npm.cmd run dev
```

开发服务默认监听 `5173`，`/api` 会代理到 `http://127.0.0.1:8008`。
