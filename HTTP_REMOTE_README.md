# DropMp3 HTTPリモコン追加メモ

この版では、起動中のDropMp3をブラウザから操作する
HTTPリモコンを追加しています。

## 使い方

DropMp3を起動すると、HTTPリモコンが有効になります。
ログに次のようなURLが出ます。

```text
[REMOTE] listening: http://127.0.0.1:8765/
[REMOTE] LAN URL: http://192.168.x.x:8765/
```

同じPCなら `http://127.0.0.1:8765/` を開きます。
別PCやスマホから操作する場合は、LAN URLを開きます。

タスクトレイメニューにも「HTTPリモコンを開く」を追加しています。

## できること

- 現在のプレイリスト表示
- 指定インデックスの再生
- 再生 / 一時停止 / 停止
- 前へ / 次へ
- 音量変更
- シーク

音はDropMp3が起動しているPCから鳴ります。
ブラウザ側へ音声ストリームを転送する機能ではありません。

## 設定

`_conf/DropMp3.ini` の `[remote]` で変更できます。

```ini
[remote]
enabled=true
host=0.0.0.0
port=8765
token=
```

`host=0.0.0.0` はLAN内からも受け付けます。
外から触れる環境では `token` を設定してください。

例:

```ini
token=your-secret-token
```

この場合は、ブラウザで次のように開きます。

```text
http://192.168.x.x:8765/?token=your-secret-token
```

## 注意

LAN内の別端末からアクセスできない場合は、
Windows Defender FirewallでPythonまたは作成したExeの
受信許可が必要です。
