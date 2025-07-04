# Zabbix 模板替换工具使用说明

## 工具概述

template_replacer.py是一个功能强大的 Zabbix 模板替换工具，专门用于在 Zabbix 环境中进行模板的批量替换和管理。该工具不仅能够替换模板，还能检测和处理模板替换后产生的非模板触发器，确保系统的稳定性和一致性。

## 主要功能

### 1. 模板替换功能
- **主机组批量替换**：在指定主机组中查找使用特定模板的主机，并批量替换为新模板
- **单主机替换**：支持通过主机名或主机ID对单个主机进行模板替换
- **智能模板管理**：保留主机的其他模板，只替换指定的目标模板

### 2. 非模板触发器检测与清理
- **自动检测**：模板替换后自动检测产生的非模板触发器
- **详细报告**：生成包含触发器详细信息的CSV报告
- **交互式删除**：提供多种删除选项（全部删除、选择性删除、跳过删除）
- **独立检查**：支持单独检查主机或主机组的非模板触发器

### 3. 完整的日志记录
- **操作日志**：记录所有操作过程和结果
- **错误处理**：详细的错误信息和异常处理
- **进度跟踪**：实时显示操作进度和状态

## 系统要求

- **Python 版本**：Python 3.6+
- **Zabbix 版本**：支持 Zabbix 7.2+ (使用 Bearer Token 认证)
- **网络要求**：能够访问 Zabbix API 接口

## 安装依赖

```bash
pip install requests
```

## 配置说明

工具使用硬编码配置，位于template_replacer.py 类中：

```python:/Users/yuexixi/code/zabbix/template_replacer.py
class ZabbixConfig:
    def __init__(self):
        self.url = "http://localhost/api_jsonrpc.php"  # Zabbix API 地址
        self.user = "Admin"                          # 用户名
        self.password = "zabbix"                     # 密码
        self.timeout = 30                            # 超时时间(秒)
```

**使用前请根据实际环境修改配置参数。**

## 使用方法

### 1. 主机组模板替换

在指定主机组中将所有使用旧模板的主机替换为新模板：

```bash
python3 template_replacer.py group <主机组名> <旧模板名> <新模板名> [--check-triggers]
```

**示例：**
```bash
# 基本替换
python3 template_replacer.py group "生产环境" "Template Linux Old" "Template Linux New"

# 替换并检查非模板触发器
python3 template_replacer.py group "测试环境" "Template App MySQL" "Template App MySQL v2" --check-triggers
```

### 2. 单主机模板替换（按主机名）

为指定名称的主机替换模板：

```bash
python3 template_replacer.py host-name <主机名> <旧模板名> <新模板名> [--check-triggers]
```

**示例：**
```bash
# 为特定主机替换模板
python3 template_replacer.py host-name "web-server-01" "Template Web Server" "Template Web Server v2"

# 替换并检查触发器
python3 template_replacer.py host-name "db-server-01" "Template DB" "Template DB Enhanced" --check-triggers
```

### 3. 单主机模板替换（按主机ID）

为指定ID的主机替换模板：

```bash
python3 template_replacer.py host-id <主机ID> <旧模板名> <新模板名> [--check-triggers]
```

**示例：**
```bash
# 使用主机ID进行替换
python3 template_replacer.py host-id "10001" "Template Linux" "Template Linux v2" --check-triggers
```

### 4. 非模板触发器检查

独立检查主机或主机组的非模板触发器：

```bash
# 检查单个主机
python3 template_replacer.py check-triggers <主机名>

# 检查主机组
python3 template_replacer.py check-triggers <主机组名> --by-group
```

**示例：**
```bash
# 检查单个主机的非模板触发器
python3 template_replacer.py check-triggers "web-server-01"

# 检查整个主机组的非模板触发器
python3 template_replacer.py check-triggers "生产环境" --by-group
```

## 参数说明

| 参数 | 说明 |
|------|------|
| `--check-triggers` | 在模板替换后检查并可选择删除非模板触发器 |
| `--by-group` | 与 `check-triggers` 配合使用，按主机组检查 |

## 输出文件

### 1. 日志文件

- **文件名**：`template_replace.log`
- **内容**：包含所有操作的详细日志，包括成功、失败和错误信息
- **编码**：UTF-8

### 2. 非模板触发器报告

- **文件名**：`non_template_triggers_YYYYMMDD_HHMMSS.csv`
- **格式**：CSV 格式，UTF-8 编码
- **字段说明**：

| 字段名 | 说明 |
|--------|------|
| 主机名 | 触发器所属主机的名称 |
| 主机ID | 触发器所属主机的ID |
| 触发器ID | 触发器的唯一标识符 |
| 触发器描述 | 触发器的描述信息 |
| 表达式 | 触发器的表达式 |
| 优先级 | 触发器优先级（未分类/信息/警告/一般严重/严重/灾难） |
| 状态 | 触发器状态（启用/禁用） |
| 监控项名称 | 关联监控项的名称 |
| 监控项键值 | 关联监控项的键值 |

## 非模板触发器处理

### 什么是非模板触发器？

非模板触发器是指直接在主机上创建的触发器，而不是从模板继承的触发器。这些触发器在模板替换后可能会产生以下问题：

- **配置不一致**：与新模板的监控策略不符
- **重复监控**：与新模板中的触发器功能重复
- **维护困难**：无法通过模板统一管理

### 处理选项

当检测到非模板触发器时，工具会提供以下选项：

1. **删除所有非模板触发器**：一次性删除所有检测到的非模板触发器
2. **手动选择删除**：查看详细列表，选择性删除特定的触发器
3. **跳过删除**：保留所有非模板触发器，仅生成报告

### 交互式删除界面

```
============================================================
检测到非模板触发器！
详细信息请查看报告文件: non_template_triggers_20240101_120000.csv
共发现 5 个非模板触发器
============================================================

前5个触发器预览:
1. 主机: web-server-01 | 触发器: CPU使用率过高 | 优先级: 警告
2. 主机: web-server-01 | 触发器: 磁盘空间不足 | 优先级: 严重
3. 主机: db-server-01 | 触发器: 数据库连接异常 | 优先级: 灾难
...

请选择操作:
1. 删除所有非模板触发器
2. 手动选择删除
3. 跳过删除

请输入选择 (1/2/3):
```

## 使用示例

### 示例1：生产环境模板升级

```bash
# 将生产环境主机组中的旧Linux模板替换为新版本
python3 template_replacer.py group "生产环境" "Template OS Linux" "Template OS Linux v2" --check-triggers
```

**执行过程：**
1. 连接到Zabbix API
2. 查找"生产环境"主机组
3. 找到使用"Template OS Linux"模板的所有主机
4. 逐个替换为"Template OS Linux v2"模板
5. 检查替换后的非模板触发器
6. 生成详细报告并提供删除选项

### 示例2：单主机紧急修复

```bash
# 为特定主机紧急替换有问题的模板
python3 template_replacer.py host-name "critical-server" "Template Faulty" "Template Fixed"
```

### 示例3：非模板触发器审计

```bash
# 检查整个数据库主机组的非模板触发器
python3 template_replacer.py check-triggers "数据库服务器" --by-group
```

## 日志文件说明

### 日志级别

- **INFO**：正常操作信息
- **WARNING**：警告信息（如主机未使用指定模板）
- **ERROR**：错误信息（如连接失败、操作失败）

### 日志示例

```
2024-01-01 12:00:00,123 - INFO - 正在登录 Zabbix...
2024-01-01 12:00:01,456 - INFO - 登录成功
2024-01-01 12:00:02,789 - INFO - 开始在主机组 '生产环境' 中替换模板
2024-01-01 12:00:03,012 - INFO - 旧模板: Template OS Linux
2024-01-01 12:00:03,345 - INFO - 新模板: Template OS Linux v2
2024-01-01 12:00:04,678 - INFO - 找到 10 个主机需要替换模板
2024-01-01 12:00:05,901 - INFO - 主机 'web-server-01' 模板替换成功
2024-01-01 12:00:06,234 - INFO - 模板替换完成: 10/10 个主机成功
2024-01-01 12:00:07,567 - INFO - 开始检查迁移后的非模板触发器...
2024-01-01 12:00:08,890 - INFO - 发现 3 个非模板触发器
2024-01-01 12:00:09,123 - INFO - 详细报告已保存到: non_template_triggers_20240101_120009.csv
```

## 错误处理

### 常见错误及解决方案

1. **连接错误**
   ```
   ERROR - 无法连接到 Zabbix 服务器: http://localhost/api_jsonrpc.php
   ```
   - 检查Zabbix服务器地址是否正确
   - 确认Zabbix服务是否正常运行
   - 检查网络连接

2. **认证错误**
   ```
   ERROR - 登录失败: Zabbix API 错误: Login name or password is incorrect
   ```
   - 检查用户名和密码是否正确
   - 确认用户是否有足够的权限

3. **资源不存在错误**
   ```
   ERROR - 主机组 '不存在的组' 不存在
   ERROR - 旧模板 '不存在的模板' 不存在
   ```
   - 检查主机组名称是否正确
   - 确认模板名称是否存在
   - 注意名称的大小写敏感性

4. **权限错误**
   ```
   ERROR - Zabbix API 错误: No permissions to referred object or it does not exist!
   ```
   - 确认用户有足够的权限访问相关资源
   - 检查用户组权限设置

## 最佳实践

### 1. 操作前准备
- **备份配置**：在进行大规模模板替换前，建议备份Zabbix配置
- **测试环境验证**：先在测试环境中验证模板替换的效果
- **权限确认**：确保操作用户有足够的权限

### 2. 分批操作
- **小批量测试**：对于大量主机，建议先选择少量主机进行测试
- **分时段操作**：避免在业务高峰期进行大规模操作
- **逐步推进**：按主机组或业务模块逐步进行替换

### 3. 监控和验证
- **实时监控**：替换过程中密切关注日志输出
- **功能验证**：替换后验证监控功能是否正常
- **告警测试**：确认新模板的告警规则是否生效

### 4. 非模板触发器处理
- **仔细审查**：在删除非模板触发器前，仔细审查报告内容
- **业务确认**：与业务团队确认哪些触发器可以删除
- **保留重要触发器**：对于业务关键的自定义触发器，考虑保留或迁移到模板中

## 注意事项

### 1. 安全注意事项
- **权限控制**：确保只有授权人员能够执行模板替换操作
- **操作审计**：保留操作日志用于审计和问题排查
- **回滚准备**：准备回滚方案以应对意外情况

### 2. 性能注意事项
- **API限制**：注意Zabbix API的并发限制和频率限制
- **网络延迟**：在网络延迟较高的环境中，适当增加超时时间
- **资源占用**：大规模操作时注意Zabbix服务器的资源占用

### 3. 数据一致性
- **原子操作**：每个主机的模板替换是原子操作，失败不会影响其他主机
- **状态检查**：替换前会检查主机和模板的存在性
- **错误恢复**：单个主机操作失败不会中断整个批量操作

## 技术支持

如果在使用过程中遇到问题，请：

1. **查看日志**：首先检查 `template_replace.log` 文件中的详细错误信息
2. **检查配置**：确认 template_replacer.py中的配置参数
3. **验证环境**：确认Zabbix服务器状态和网络连接
4. **权限检查**：验证用户权限和API访问权限

该工具为Zabbix模板管理提供了强大而灵活的解决方案，通过自动化的模板替换和智能的触发器管理，大大简化了Zabbix环境的维护工作。
        