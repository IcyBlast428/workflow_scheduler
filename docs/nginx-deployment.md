# 独立 Nginx / Docker 代理访问

访问链路示例为 `http://wfs.example.com:8000/` → Nginx 机器 → `http://192.0.2.10:8008/`。部署时将示例域名和 IP 替换为现场地址，并将域名解析到 Nginx 机器。若平台位于另一台服务器，在代理目标中填写其实际地址。

平台先按 [首次投产手册](../START-HERE.md) 完成启动。在 Nginx 机器核对到平台 8008 的连通性；平台的 8009 仅供本机进程通信，不代理、不对外开放。

## 配置与端口

使用 [wfs.conf 模板](../deploy/nginx/wfs.conf)，放入现有 Nginx 的 `http` 配置上下文，例如挂载至容器 `/etc/nginx/conf.d/wfs.conf`。模板监听 **容器内 8000**，Docker 对应发布 **宿主机 8000 → 容器 8000**（`8000:8000`）。

如果已有容器实际映射为 `8000:80`，模板应改成 `listen 80;`。容器内使用 80 不代表占用宿主机 80；宿主机对外端口由 Docker 映射决定。不要为了本平台覆盖现有 Nginx 的其他站点或另起一个占用相同宿主端口的容器。

Nginx 将整个 `/` 路径交给 Web，包括 `/admin/`、`/api/` 和静态资源，无需另行复制前端文件。模板保留包含 `:8000` 的 Host，代理超时不等于任务运行超时。指令依据 [Nginx 官方代理模块文档](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)。

## 检查与生效

将下方容器名 `nginx` 替换为实际名称。在配置文件已经挂载进容器后执行：

```bash
docker port nginx
docker exec nginx nginx -t
# 仅在上一条检查成功后执行
docker exec nginx nginx -s reload
```

如果需要改变 Docker 端口发布规则，应由现有容器的部署配置进行变更；仅 reload Nginx 不会修改 Docker 端口映射。

浏览器使用现场代理域名和端口打开平台，验证登录、任务列表和日志读取。HTTP 访问保持平台 `WFS_COOKIE_SECURE=false`。启用 HTTPS 时同步核对证书、代理和 Cookie 设置。

502 时先检查 Nginx 容器是否能连接平台 IP:8008、平台服务是否就绪；登录失败时核对代理 Host、访问协议与平台日志。不要把服务恢复或任务重跑与刷新浏览器混为一谈。
