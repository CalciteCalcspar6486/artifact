# ARTIFACT · 异想艺术档案馆

一本每天更新的艺术小刊。打开「今日」看本期封面，点图查看大图。用分类切换游戏美术、像素艺术、异想艺术和音乐。「往期」可以按日期翻阅。音乐卡片会打开原站播放。

## 上线到 GitHub Pages

1. 解压项目包。登录 [GitHub](https://github.com/)，点击右上角 **＋ → New repository**。名称填 `artifact`，选 **Public**，勾选 **Add a README file**，再点 **Create repository**。
2. 在仓库的 **Code → Add file → Upload files**，从资源管理器把解压后的 `ARTIFACT` **里面的文件和子文件夹**全部拖入上传区，包含 `.github`。确认上传列表有 `.github/workflows/daily.yml`，然后提交到 `main`。若界面只允许新建分支，就按提示创建并合并拉取请求。
3. 打开 **Settings → Pages → Build and deployment**，将 **Source** 设为 **GitHub Actions**。
4. 打开 **Actions → ARTIFACT daily → Run workflow**，选择 `main` 后再点 **Run workflow**。若显示 **Enable workflow**，先启用。运行变绿后，从 **Settings → Pages → Visit site** 打开网站。

提交后的仓库根目录应能直接看到 `index.html`、`data` 和 `.github`。若上传列表漏掉工作流，可用 **Code → Add file → Create new file** 新建 `.github/workflows/daily.yml`，粘贴解压包中同名文件的内容并提交。

免费方案的网站和推荐档案可公开访问。收藏只写入本机浏览器。部署后 GitHub 每天在中国时间 12:00 调度更新，繁忙时可能延迟。如果公开仓库连续 60 天没有活动，GitHub 可能停用定时任务，可在 **Actions → ARTIFACT daily** 重新启用。采集和发布由 GitHub 执行，电脑关机也能运行。 [Pages 设置](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site) · [定时任务说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

## 安装到 Android

用 Android 上的 Chrome 打开 **Visit site** 得到的 HTTPS 地址，点 **⋮ → 添加到主屏幕 → 安装**。菜单也可能直接显示 **安装应用**。之后从桌面图标打开。

离线时可以打开已缓存的页面和读过的档案。部分外部预览和原站需要联网。清除浏览器数据可能导致收藏丢失。可以在「收藏」里导出 JSON 备份，导入会合并到现有收藏。

## 选集与更新

- **itch.io** 公开 RSS 提供创作者发布的独立游戏与概念设计。应用展示官方链接预览，具体美术人员请查看原项目的署名。 [RSS 说明](https://itch.io/docs/api/overview#rss-feeds)
- **Cleveland Museum of Art** 提供 CC0 开放图像，用于补充废墟、风景和其他艺术灵感。 [开放 API](https://openaccess-api.clevelandart.org/)
- **OC ReMix** 的近期 RSS 和历史曲库提供游戏音乐改编。封面使用原站指定的分享预览，音频留在原平台。 [RSS](https://ocremix.org/info/Feeds) · [曲库](https://ocremix.org/remixes/)

想调整口味，可以在 GitHub 打开 `scripts/preferences.json`，点铅笔编辑关键词权重或搜索主题。分数代表来源和主题的匹配程度。每日目标是 10 件视觉作品与 4 首音乐，作品页或预览失效时会跳过，允许少收。推荐按日期写入 `data/archive`，历史用于去重。同日重跑保留已生成的选集。全部来源失败或没有新作品时，上次发布的页面保持可访问。

本地预览可在解压后的 `ARTIFACT` 文件夹运行 `python -m http.server 8000`，再打开 [本地地址](http://localhost:8000/)。采集使用 Python 标准库。用 `python scripts/collect.py` 采集，或用 `python -m unittest discover -s scripts` 检查去重和失败恢复。
