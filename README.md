# Collection image delivery

IIIF Image API 3（子集）纯后端：按区域与倍率从本地清单提供馆藏扫描图。

## 启动

```bash
.venv/bin/python scripts/make_samples.py   # 生成示例图与 data/manifest.json
.venv/bin/python -m uvicorn app.main:app --port 8000
```

环境变量：`IMAGE_ROOT`、`MANIFEST_PATH`、`CACHE_DIR`、`CACHE_MAX_BYTES`、
`MAX_PIXELS`（解码像素上限，默认 1 亿）、`MAX_PARALLEL`（并行图像计算数，默认 4）。

## 接口

- `GET /iiif/3/{id}/info.json` — 服务文档（真实宽高、level1、gray/png/mirroring 等能力声明）
- `GET /iiif/3/{id}/{region}/{size}/{rotation}/{quality}.{format}`
  - region: `full` \| `x,y,w,h` \| `pct:x,y,w,h`
  - size: `max` \| `w,` \| `,h` \| `!w,h`（禁止放大）
  - rotation: `0/90/180/270`，前置 `!` 先水平镜像
  - quality: `default` \| `gray`；format: `jpg` \| `png`

处理顺序：EXIF 转正 → 裁切 → 缩放 → 镜像 → 顺时针旋转 → 灰度。

## curl 演示

```bash
curl -s localhost:8000/iiif/3/photo/info.json
curl -OJ localhost:8000/iiif/3/photo/100,100,400,300/!200,200/0/default.jpg
curl -OJ 'localhost:8000/iiif/3/overlay/pct:10,10,50,50/,300/!90/gray.png'
ETAG=$(curl -sD- -o/dev/null localhost:8000/iiif/3/photo/full/max/0/default.jpg | awk '/^[Ee]tag/{print $2}' | tr -d '\r')
curl -o /dev/null -w '%{http_code}\n' -H "If-None-Match: $ETAG" localhost:8000/iiif/3/photo/full/max/0/default.jpg  # 304
```

## 自测

```bash
.venv/bin/python -m pytest tests/ -q
```

## 边界与安全

- 仅服务清单内、根目录内的 PNG/JPEG；`..` 越界与符号链接逃逸返回 404；不接受远程地址与上传。
- 区域超出右/下边界时裁到边缘；完全在外或零面积返回 400；非法数字/参数 400；损坏图 422；超像素上限 413。
- 透明图导出 JPEG 时合成白底。
- 衍生图写入 `.cache/derivatives`，磁盘 LRU 按字节容量淘汰；同键并发只渲染一次；
  临时文件 + `os.replace` 原子发布，失败不留半成品。缓存键含源文件 mtime+size，
  源文件原子替换后旧在途结果不会污染新版本。
- ETag/`If-None-Match` 命中返回无正文 304；`Cache-Control: no-cache` 保证每次协商。

## 结构

- `app/manifest.py` — 清单读取与安全路径解析
- `app/iiif.py` — IIIF 参数解析与校验
- `app/transform.py` — 解码与变换管线
- `app/cache.py` — 磁盘 LRU 缓存与单飞锁
- `app/main.py` — FastAPI 路由、ETag、并发限制

