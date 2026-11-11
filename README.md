# 東京の町、勝手にPR — 投稿パイプライン

`queue/<slug>/` に `video.mp4` と `caption.txt` を置いて push すると、承認待ちになります。
GitHub（アプリ/メール）の通知から **Approve** すると Instagram（@tokyo_katteni_pr）にリールとして投稿され、`posted/<slug>/` に移動して `result.json`（投稿URL）が残ります。

- 接続テスト: Actions → 「接続テスト（投稿はしない）」→ Run workflow
- トークン: Secrets `IG_ACCESS_TOKEN`（コード・ログには出しません）
- 承認者: Settings → Environments → `instagram` → Required reviewers
