---
type: ai-news
channel: Matt Wolfe
video_id: -KcHn0QcSb0
published: 
collected: 2026-09-11
url: https://www.youtube.com/watch?v=-KcHn0QcSb0
source: video
tags: [jibun-ai, ai-news, video]
---

# Trying To Solve The Biggest AI Problem

**公開日: **（取得: 2026-09-11）
出典: https://www.youtube.com/watch?v=-KcHn0QcSb0

## 動画から起こした解説

この動画では、動画がAIによって作られたものかを判別するウェブアプリ「AI Slop Detector（AI検出器）」の作成と機能が紹介されています。このツールは、InstagramやTikTok、YouTube、X（旧Twitter）の動画URLを入力するか、動画ファイルを直接アップロードすることで、動画にAIの痕跡があるかを解析し、AI製である可能性を検出することができます。

具体的な手順と使い方は以下の通りです。まず開発プロセスとして、ChatGPTに開発アイデアを伝え、GoogleのAIモデル「Gemini（ジェミニ）」と、動画解析サービス「Sightengine（サイトエンジン）」のAPI（システムを連携させる仕組み）を組み合わせる方針を決めます。次に、ChatGPTのプログラミング機能を用いてAIに直接コードを作成させます。Sightengineから取得したAPIキー（連携用パスワード）を設定ファイル「.env.local」に保存し、プログラムを起動します。AIにテストを繰り返させ、検出精度の高いSightengineの解析結果を優先させるように調整を行いました。
実際の使い方はシンプルです。ブラウザでツールの画面を開き、「Paste link（リンクを貼り付け）」欄に解析したい動画のURLを入力するか、または「Upload video（ビデオをアップロード）」から動画ファイルを選択します。そして「Scan video（スキャン実行）」ボタンを押します。数分間のスキャン後、AI動画の可能性が高ければ「AI INDICATORS DETECTED（痕跡あり）」、AIではないと判断されれば「NO CLEAR AI INDICATORS（痕跡なし）」、判断が分かれた場合は「INCONCLUSIVE（判定不能）」と結果が出力されます。

料金については、システムとして使うSightengineの無料プランには動画解析機能が含まれていません。そのため有料プランの契約が必要となり、動画解析が可能なプランは、スタータープランが月額29ドル、プロプランが月額99ドルです。動画1回の解析で数百回分の処理数が消費されます。

注意点として、APIの消費が多く運営コストがかさむため、誰でも自由に使える公開ウェブサイトとしては提供されていません。実際に使用するには、GitHub（プログラムの共有サイト）からコードを自身のパソコンにダウンロードし、自分で用意した有料のAPIキーを設定して実行する必要があります。また、検出精度は完璧ではなく、明らかにAIで作られた動画であっても「判定不能」と誤認することもあります。
