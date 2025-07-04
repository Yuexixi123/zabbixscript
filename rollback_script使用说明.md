
# Zabbix 主机组回滚脚本使用说明

## 工具概述

rollback_script.py是一个专门用于回滚 Zabbix 主机组配置的工具脚本。该脚本能够将主机组名称和主机关联关系恢复到备份时的状态，是 zabbix_group_update.py 工具的配套回滚工具。

## 主要功能

### 1. 自动备份文件检测
- 自动扫描当前目录下的备份文件（`group_backup_*.json`）
- 按修改时间排序，默认选择最新的备份文件
- 显示所有可用备份文件供用户确认

### 2. 主机组名称回滚
- 将主机组名称恢复到备份时的状态
- 支持重新创建已删除的主机组
- 保持主机组 ID 的一致性

### 3. 主机关联关系恢复
- 恢复主机到原始主机组的关联关系
- 自动从"下线"分组中移除主机
- 确保主机至少属于一个分组

### 4. 完整的日志记录
- 详细记录回滚操作过程
- 记录成功和失败的操作
- 生成 `rollback.log` 日志文件

## 系统要求

- Python 3.6+
- 依赖zabbix_group_update.py模块
- 有效的 Zabbix API 访问权限
- 存在备份文件（`group_backup_*.json`）

## 使用方法

### 基本使用

```bash
python3 rollback_script.py
```

### 使用流程

1. **运行脚本**
   ```bash
   python3 rollback_script.py
   ```

2. **查看备份文件列表**
   脚本会自动显示所有可用的备份文件：
   ```
   找到 3 个备份文件：
     1. group_backup_20250702_162519.json (最新)
     2. group_backup_20250702_162026.json
     3. group_backup_20250702_154650.json
   ```

3. **确认回滚操作**
   ```
   准备使用备份文件进行回滚：group_backup_20250702_162519.json
   确认要执行回滚操作吗？这将恢复所有分组到备份时的状态 (y/N):
   ```

4. **输入确认**
   - 输入 `y` 确认执行回滚
   - 输入 `N` 或其他字符取消操作

## 备份文件格式

脚本使用的备份文件格式为 JSON，结构如下：

```json
{
  "原主机组名称": {
    "groupid": "主机组ID",
    "hosts": [
      {
        "hostid": "主机ID",
        "name": "主机名称"
      }
    ]
  }
}
```

### 备份文件示例

```json
{
  "Linux服务器组": {
    "groupid": "123",
    "hosts": [
      {
        "hostid": "10001",
        "name": "web-server-01"
      },
      {
        "hostid": "10002",
        "name": "db-server-01"
      }
    ]
  },
  "Windows服务器组": {
    "groupid": "124",
    "hosts": [
      {
        "hostid": "10003",
        "name": "win-server-01"
      }
    ]
  }
}
```

## 回滚操作详解

### 1. 主机组处理流程

```python:/Users/yuexixi/code/zabbix/rollback_script.py
def rollback_group_names(backup_file, auth_token):
    # ... existing code ...
    for old_name, info in backup.items():
        groupid = info['groupid']
        # 检查主机组是否存在
        result = call_api("hostgroup.get", {
            "output": ["groupid", "name"],
            "groupids": [groupid]
        }, auth_token)
        
        if not result:
            # 重新创建已删除的主机组
            created = call_api("hostgroup.create", {"name": old_name}, auth_token)
            # 恢复主机关联
            restore_hosts_to_group(info['hosts'], new_groupid, old_name, auth_token)
        else:
            # 回滚主机组名称
            current_name = result[0]['name']
            if current_name != old_name:
                call_api("hostgroup.update", {
                    "groupid": groupid,
                    "name": old_name
                }, auth_token)
    # ... existing code ...
```

### 2. 主机关联恢复流程

<mcsymbol name="restore_hosts_to_group" filename="rollback_script.py" path="/Users/yuexixi/code/zabbix/rollback_script.py" startline="75" type="function"></mcsymbol> 函数负责恢复主机关联：

- 获取主机当前的所有分组关联
- 移除"下线"分组的关联
- 确保主机关联到目标分组
- 保证主机至少属于一个分组

## 输出示例

### 成功回滚示例

```
开始回滚操作，备份文件：group_backup_20250702_162519.json
共有 5 个分组需要处理

[回滚检查] 原分组名: 'Linux服务器组'，groupid: 123
[检查名称] 当前名称：'Linux服务器组-新'，目标：'Linux服务器组'
[恢复主机] 开始恢复 3 个主机到分组 'Linux服务器组'
[恢复主机] ID: 10001, 名称: web-server-01, 结果: 成功
[恢复主机] ID: 10002, 名称: db-server-01, 结果: 成功
[恢复主机] ID: 10003, 名称: app-server-01, 结果: 成功
[回滚成功] 分组 'Linux服务器组-新' -> 'Linux服务器组'

[回滚检查] 原分组名: 'Windows服务器组'，groupid: 124
[缺失] 分组ID 124 不存在，尝试重新创建分组 'Windows服务器组'
[回滚] 已重新创建分组 'Windows服务器组'，ID: 125
[恢复主机] 开始恢复 2 个主机到分组 'Windows服务器组'
[恢复主机] ID: 10004, 名称: win-server-01, 结果: 成功
[恢复主机] ID: 10005, 名称: win-server-02, 结果: 成功

✅ 回滚操作完成！
成功: 5 个分组
失败: 0 个分组
```

### 部分失败示例

```
✅ 回滚操作完成！
成功: 4 个分组
失败: 1 个分组
详细错误信息请查看 rollback.log 文件
```

## 日志文件

### 日志文件位置
- **文件名：** `rollback.log`
- **编码：** UTF-8
- **位置：** 脚本运行目录

### 日志内容示例

```
2024-01-15 14:30:15,123 - INFO - [回滚成功] 分组 'Linux服务器组-新' -> 'Linux服务器组'
2024-01-15 14:30:15,456 - INFO - [恢复主机] ID: 10001, 名称: web-server-01, 结果: 成功
2024-01-15 14:30:15,789 - ERROR - [回滚失败] 分组 'Test组': API错误: 权限不足
2024-01-15 14:30:16,012 - INFO - [回滚] 已重新创建分组 'Windows服务器组'，ID: 125
```

## 错误处理

### 常见错误及解决方案

#### 1. 备份文件不存在

**错误信息：**
```
错误：未找到任何备份文件 (group_backup_*.json)
```

**解决方案：**
- 确认当前目录下存在备份文件
- 检查备份文件命名格式是否正确
- 确认之前已运行过 <mcfile name="zabbix_group_update.py" path="/Users/yuexixi/code/zabbix/zabbix_group_update.py"></mcfile> 并生成了备份

#### 2. API 权限不足

**错误信息：**
```
[回滚失败] 分组 'xxx': API错误: 权限不足
```

**解决方案：**
- 确认 Zabbix 用户具有主机组管理权限
- 检查用户角色配置
- 联系 Zabbix 管理员分配相应权限

#### 3. 主机关联失败

**错误信息：**
```
[主机恢复失败] ID: 10001, 名称: server-01, 错误: 主机不存在
```

**解决方案：**
- 检查主机是否已被删除
- 确认主机 ID 的有效性
- 考虑手动重新创建主机

## 安全注意事项

### 1. 操作前确认
- 仔细确认要使用的备份文件
- 了解回滚操作的影响范围
- 在测试环境中先行验证

### 2. 备份管理
- 定期清理过期的备份文件
- 保留重要时间点的备份
- 建立备份文件的版本管理

### 3. 权限控制
- 限制脚本的执行权限
- 使用专门的回滚账户
- 记录所有回滚操作

## 最佳实践

### 1. 回滚前准备
- 确认当前配置状态
- 评估回滚的必要性和影响
- 通知相关人员

### 2. 回滚执行
- 选择业务低峰期执行
- 逐步验证回滚结果
- 监控系统状态

### 3. 回滚后验证
- 检查主机组配置
- 验证主机关联关系
- 确认监控功能正常

## 与其他工具的关系

### 依赖关系
- **依赖：** <mcfile name="zabbix_group_update.py" path="/Users/yuexixi/code/zabbix/zabbix_group_update.py"></mcfile>
- **函数调用：** `get_auth_token()`, `call_api()`
- **配置共享：** 使用相同的 Zabbix 连接配置

### 工作流程
1. 使用zabbix_group_update.py进行主机组批量操作
2. 自动生成备份文件 `group_backup_*.json`
3. 如需回滚，使用 rollback_script.py 恢复配置

## 技术支持

如遇到问题，请检查：
1. 日志文件 `rollback.log` 中的详细错误信息
2. 备份文件的完整性和格式
3. Zabbix API 的连接状态和权限
4. 主机和主机组的当前状态

该脚本为 Zabbix 主机组管理提供了可靠的回滚机制，确保配置变更的可逆性和系统的稳定性。
        