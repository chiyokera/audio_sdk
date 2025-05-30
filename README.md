# Audio SDK - AIコールセンターシステム

シナモン・チョコレート社のAIコールセンターシステムです。音声とテキストの両方でカスタマーサポートを提供するマルチエージェントシステムです。

## 概要

このプロジェクトは、OpenAI Agents SDKを使用して構築されたインテリジェントなコールセンターシステムです。複数の専門エージェントが協調して、顧客の問い合わせに対応します。

### 主な機能

- **音声コールセンター**: リアルタイム音声認識・合成による対話
- **テキストコールセンター**: チャット形式での顧客対応
- **マルチエージェントシステム**: 専門分野別のエージェントによる効率的な対応
- **商品情報管理**: 10種類の商品に関する詳細情報の提供
- **Slack連携**: 注文管理やエスカレーション通知

## システム構成

### エージェント構成

1. **トリアージエージェント**
   - 顧客の問い合わせを適切な専門エージェントに振り分け
   - 顧客情報の管理
   - 異常な質問の検出とガードレール機能

2. **商品取り扱いエージェント**
   - 商品の機能、操作方法、仕様に関する質問対応
   - 商品情報ファイルからの情報抽出

3. **商品注文・購入対応エージェント**
   - 商品の注文・購入プロセスの支援
   - Slack経由での注文管理システム連携

4. **エラー・トラブル・クレーム対応エージェント**
   - 技術的問題の解決支援
   - クレーム対応とエスカレーション

### 対応商品

- タブレット A68 Air
- スマートウォッチ B27 Max
- スマートフォン C82 Lite
- スマートスピーカー D47 Air
- スマートフォン E51 Mini
- スマートスピーカー F29 Pro
- スマートフォン G81 Standard
- ワイヤレスイヤホン H61 Air
- ワイヤレスイヤホン I79 Pro
- ゲーム機 J87 Max

## 必要な環境

### システム要件

- Python 3.13以上
- Node.js (npx コマンドが必要)
- Poetry (依存関係管理)

### 必要な環境変数

`.env` ファイルを作成し、以下の環境変数を設定してください：

```env
OPENAI_API_KEY=your_openai_api_key
SLACK_BOT_TOKEN=your_slack_bot_token
SLACK_TEAM_ID=your_slack_team_id
SLACK_CHANNEL_ID=your_slack_channel_id
```

## インストール

1. リポジトリをクローン
```bash
git clone <repository-url>
cd audio_sdk
```

2. 依存関係をインストール
```bash
poetry install
```

3. 環境変数を設定
```bash
cp .env.example .env
# .envファイルを編集して必要な値を設定
```

## 使用方法

### テキストコールセンターの起動

```bash
poetry run python src/audio_sdk/text_call_center/call_center.py
```

### 音声コールセンターの起動

```bash
poetry run python src/audio_sdk/voice_call_center/voice_call_center.py
```

### 音声コールセンターの操作方法

- **K キー**: 録音開始/停止
- **Q キー**: アプリケーション終了

## プロジェクト構造

```
audio_sdk/
├── src/
│   └── audio_sdk/
│       ├── text_call_center/
│       │   └── call_center.py          # テキストベースのコールセンター
│       └── voice_call_center/
│           ├── voice_call_center.py    # 音声コールセンターUI
│           ├── my_workflow.py          # 音声ワークフロー定義
│           └── config.py               # 音声設定
├── data/
│   ├── call_center_manual.txt          # コールセンター対応マニュアル
│   ├── products/                       # 商品情報ファイル
│   └── qa/                            # Q&Aデータ
├── tests/                             # テストファイル
├── pyproject.toml                     # プロジェクト設定
└── README.md
```

## 技術スタック

- **OpenAI Agents SDK**: マルチエージェントシステムの構築
- **Textual**: テキストベースのユーザーインターフェース
- **SoundDevice**: 音声入出力処理
- **Pydantic**: データバリデーション
- **MCP (Model Context Protocol)**: 外部システム連携

## 開発

### テストの実行

```bash
poetry run pytest
```

### 新しい商品の追加

1. `data/products/` ディレクトリに新しい商品情報ファイルを追加
2. `src/audio_sdk/text_call_center/call_center.py` の `PRODUCTS_LIST` を更新

### 新しいエージェントの追加

1. 新しいエージェントクラスを定義
2. 適切なハンドオフ関係を設定
3. 必要に応じてツールや MCP サーバーを追加

## トラブルシューティング

### よくある問題

1. **npx が見つからない**
   ```bash
   npm install -g npx
   ```

2. **音声デバイスが認識されない**
   - システムの音声設定を確認
   - `config.py` の音声設定を調整

3. **Slack連携が動作しない**
   - 環境変数の設定を確認
   - Slackボットの権限を確認

## ライセンス

このプロジェクトは MIT ライセンスの下で公開されています。

## 貢献

プルリクエストやイシューの報告を歓迎します。開発に参加する前に、コントリビューションガイドラインをご確認ください。

## サポート

技術的な質問や問題については、GitHubのIssuesページでお知らせください。
