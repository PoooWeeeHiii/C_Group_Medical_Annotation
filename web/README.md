# Medical Annotation Web (React + Vite)

## 开发

```bash
cd web
npm install
npm run dev
```

浏览器打开 http://127.0.0.1:5173 ，API 经 Vite 代理到 http://127.0.0.1:8000 。

后端需先启动：

```bash
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

## 生产构建

```bash
cd web
npm run build
```

产物在 `web/dist/`。后端若检测到该目录存在 `index.html`，将优先托管 React 构建，否则回退到旧版 `frontend/` Vanilla SPA。

## 结构

- `src/pages/` — 9 个业务页
- `src/auth/` — 登录会话
- `src/api/` — fetch 封装
- `src/components/` — 布局 / Toast / 登录
- `public/volume_viewer.js` — 既有 WebGL 3D 模块（可按需动态加载）
