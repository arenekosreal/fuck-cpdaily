# 今日校园自动化

## 简介

自动化重复的签到和问卷提交过程，基于[ZimoLoveShuang](https://github.com/ZimoLoveShuang)大佬的相关项目编写。

## 特性

1. 放弃API登陆而使用requests本地模拟登陆以防哪天API翻车
2. `apis.json`存储部分可能随今日校园程序版本更新而改变的额外数据，方便日后替换而不影响代码本体（大概）
3. 验证码使用OCR本地识别，也提供手动识别的流程代码，默认未开启，而且验证码一般不会出现，除非密码错误次数大于3次

## 依赖

在`requirements.txt`内，执行`pip install -r requirements.txt`完成安装。由于tensorflow不支持3.9，因此目前为止最高支持3.8的Python，当tensorflow支持3.9的时候也可以直接在3.9的Python上使用

## 配置文件

参考[ZimoLoveShuang](https://github.com/ZimoLoveShuang)大佬的两个相关项目的配置文件编写，不过是json格式的文件，文件名为`config.json`，以后应该会加上一个生成器

## 当前状态

只完成了CLOUD登陆及签到信息的获取和提交，未适配云函数，但可以自己进行简单更改即可适配

## 目标

1. 完成NOTCLOUD方式兼容
2. 完成信息收集部分的自动化
