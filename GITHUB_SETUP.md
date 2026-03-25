# GitHub 上传指南

## 前置条件

1. 安装 Git：https://git-scm.com/
2. 创建 GitHub 账户：https://github.com/signup
3. 生成 SSH Key 或配置 Personal Access Token

## 上传步骤

### 1. 创建私有仓库

在 GitHub 上：
- 点击 "New repository"
- 输入仓库名：`tiktok-analyzer`
- 选择 "Private"（私有）
- 点击 "Create repository"

### 2. 添加远程仓库

```bash
cd E:/tiktok_analyzer
git remote add origin https://github.com/YOUR_USERNAME/tiktok-analyzer.git
git branch -M main
git push -u origin main
```

### 3. 验证上传

访问 https://github.com/YOUR_USERNAME/tiktok-analyzer

## 配置私有仓库

### 访问权限设置

1. 进入仓库 Settings
2. 左侧选择 "Collaborators"
3. 添加需要访问的用户

### 分支保护

1. Settings → Branches
2. 添加规则保护 main 分支
3. 要求 Pull Request 审查

## 常用命令

```bash
# 查看状态
git status

# 提交更改
git add .
git commit -m "描述"
git push

# 拉取更新
git pull

# 创建分支
git checkout -b feature/new-feature
git push -u origin feature/new-feature
```

## 注意事项

- ✓ 确保 config.json 不包含真实 API Key
- ✓ 使用 config.json.example 作为模板
- ✓ 定期更新依赖版本
- ✓ 添加有意义的 commit 信息
