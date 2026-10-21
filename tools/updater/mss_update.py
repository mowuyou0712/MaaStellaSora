{
	"schema": 1,
	"repo": {
		"owner": "MaaStellaSora",
		"name": "MaaStellaSora"
	},
	"api": "https://api.github.com/repos/{owner}/{repo}",
	"asset_pattern": "{name}-{platform}-{tag}.{ext}",
	"platforms": {
		"win-x86_64": "zip",
		"win-aarch64": "zip",
		"linux-x86_64": "tar.gz",
		"linux-aarch64": "tar.gz",
		"macos-x86_64": "tar.gz",
		"macos-aarch64": "tar.gz",
		"android-arm64-v8a": "apk"
	},
	"mirrors": [
		{
			"name": "gh-proxy",
			"prefix": "https://gh-proxy.com/",
			"scopes": [
				"api",
				"download"
			],
			"note": "API 与 Release 下载都可用，默认首选"
		},
		{
			"name": "gh.llkk.cc",
			"prefix": "https://gh.llkk.cc/",
			"scopes": [
				"api",
				"download"
			],
			"note": "备用镜像，API 与下载都可用"
		},
		{
			"name": "ghfast",
			"prefix": "https://ghfast.top/",
			"scopes": ["download"],
			"note": "只代理下载，API 返回 403"
		},
		{
			"name": "ghproxy.net",
			"prefix": "https://ghproxy.net/",
			"scopes": ["download"],
			"note": "只代理下载，速度不稳"
		},
		{
			"name": "直连 GitHub",
			"prefix": "",
			"scopes": [
				"api",
				"download"
			],
			"note": "本机已有代理时可用，国内直连通常失败"
		}
	],
	"protected_paths": [
		"config",
		"debug",
		"logs",
		"log",
		"cache",
		"user",
		"backup",
		".update"
	],
	"managed_dirs": [
		"resource",
		"interface",
		"i18n",
		"agent"
	]
}
