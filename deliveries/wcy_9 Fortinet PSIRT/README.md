# wcy_9 Fortinet PSIRT

采集者：wcy（武才颖，241820271）。

状态：**部分完成，采集不完整**。

窗口：2024-09-10 至 2026-09-15，不含结束日，按来源公告首次发布日期筛选，UTC 规范化。数据内容为实际抓取时的最新版本，不是截止结束日的历史快照。

已取得 345 条公告，拆成 357 条来源观测／COSV 记录，包含 352 个独立 CVE。公告数与漏洞数不同；无 CVE 公告也保留。全目录 736 条中有 183 条详情未取得，无法判断它们是否在时间窗口内；manifest 中 collection_complete=false。

优先请学长检查：FG-IR-25-667、FG-IR-25-501、FG-IR-24-535。它们编号年份较近，但编号年份不等于首次发布日期。其余失败条目也保留在 CSV 中。

## 文件

- `wcy_9 Fortinet PSIRT.zip`：对应来源全部交付数据、可运行的仓库基线和采集实现、该来源冻结响应缓存、补丁与说明；不包含另两个来源的数据。
- `overview.csv`：Excel 可直接查看的索引。
- `manifest.json`、`coverage.json`、`verification.json`：批次哈希、采集范围及验证结果。
- Fortinet 另附实际联网失败清单和 live-attempt-coverage.json，不用离线缓存缺失错误代替联网错误。

包内数据已通过批次格式、哈希、来源 ID、时间窗口和离线重放一致性检查。验证通过不代表来源全部字段齐全，也不代表 Fortinet 已采全。

## 运行

解压后在包内 `magent` 目录执行：

```powershell
python tools/collect_sources_789.py --sources fortinet --output ../replay-delivery --cache ../live-cache
```

安装依赖及接入现有任务列表的说明见 `magent/docs/PUBLIC_SOURCES_789.md`。原收集任务尚未替换；本次 PR 只新增交付目录，不改现有收集器或主分支代码。包内补丁单独保留供核对，不强行覆盖学长未推送的修改。

Fortinet 保留未完成项时命令退出码为 1，其他已采集数据仍有效。补采需要实际可访问的官方链接、公开 CSAF 文件或公告导出，不需要把账号密码、Cookie 或 API 密钥发进聊天。

来源数据须遵守发布者条款；公开可访问并不表示附带开放再分发许可。压缩包不包含账号密钥、授权请求头或 Cookie 文件。
