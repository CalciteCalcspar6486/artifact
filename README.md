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

- **像素场景**来自 OpenGameArt 的逐件精选和指定社区选集。采集社区选集时会核对 2D 类型、像素标签、场景名称、作者和独立预览。 [像素背景选集](https://opengameart.org/content/06-pixel-art-backgrounds) · [授权说明](https://opengameart.org/content/faq)
- **游戏概念稿和插画**使用 Wikimedia Commons 上逐件核验的原始文件。Ryzom 来源只读取指定的环境和植物概念档案。David Revoy 的《Sintel》作品归为开放影片的制作美术。 [游戏概念稿](https://commons.wikimedia.org/wiki/Category:Video_game_concept_art) · [Sintel 制作美术](https://commons.wikimedia.org/wiki/Category:Concept_art_by_David_Revoy_for_Sintel) · [Ryzom 制作美术](https://commons.wikimedia.org/wiki/Category:Ryzom_concept_art)
- **Cleveland Museum of Art** 的 CC0 开放馆藏用于补充艺术研究专题。只选署名清楚、标题或技法符合主题的馆藏图像。 [开放 API](https://openaccess-api.clevelandart.org/)
- **OC ReMix** 的近期 RSS 和历史曲库提供游戏音乐改编。使用曲目页提供的分享图，播放回到原站。 [RSS](https://ocremix.org/info/Feeds) · [曲库](https://ocremix.org/remixes/)

新版已停用 itch.io 游戏目录。添加喜欢的艺术家时，在 `scripts/curated_sources.json` 里复制一条 `reviewed_pages` 来源或增补其中的 `works`。先核对作品页、作者、原图和再利用许可，再启用。现有白名单适配 Wikimedia Commons 和 OpenGameArt 的作品页。新站点需要验证其访问规则和作品元数据，并为它增加对应的解析逻辑。图库的授权链接通往原始许可。

`scripts/preferences.json` 按像素、场景概念、巨构与奇异世界、角色生物、技法、氛围、实验和音乐分组。选集用可调整的主题比例、相邻风格和探索比例安排候选。关键词只辅助判断相关性和排序。作品必须先通过来源、类型、作者、原页和预览检查。这些规则无法自动判断构图、风格和作品的艺术水准。策展人仍需定期补充和审阅有限的开放作品库。

每日目标是 10 件视觉作品与 4 首音乐。结果允许少于目标，无合格视觉作品时保留上一期。推荐按日期写入 `data/archive`，通过作品页和预览地址检查本期及往期的重复。同日重跑保留已生成的选集。

在项目根目录执行 `python scripts/collect.py --diagnostic` 可输出 JSON 诊断。也可用 `--report diagnostic.json` 保存到项目根目录。诊断只模拟选件，列出候选的原链接、作者、匹配关键词、白名单、作品类型核验状态及入选、拒绝或留待后续的理由，适合测试修改后的配置。

ArtStation 的自动化访问有明确限制。Behance 和 DeviantArt 的公开说明没有提供本项目所需的免凭证且可复用预览链路。Lospec 的官方 API 需要密钥，PixelJoint 也未核实可自动复用精选图像的方式。Bandcamp 的官方接口面向已授权合作方，SoundCloud 注册应用需要 Artist Pro。本版本只启用已核实的来源，无需 API 密钥或额外付费。 [ArtStation](https://magazine.artstation.com/2026/09/ai-updates-from-artstation/) · [Behance](https://wwwimages2.adobe.com/content/dam/cc/en/legal/servicetou/Behance-Additional-Terms-en_US-20240116.pdf) · [Lospec](https://api.lospec.com/docs/) · [PixelJoint](https://pixeljoint.com/pixels/faqs.asp) · [Bandcamp](https://bandcamp.com/developer) · [SoundCloud](https://developers.soundcloud.com/docs/api/register-app.html)

本地预览可在解压后的 `ARTIFACT` 文件夹运行 `python -m http.server 8000`，再打开 [本地地址](http://localhost:8000/)。采集使用 Python 标准库。用 `python scripts/collect.py` 采集，或用 `python -m unittest discover -s scripts` 检查去重和失败恢复。
