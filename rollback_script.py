import json
import logging
import time
from zabbix_group_update import get_auth_token, call_api

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('rollback.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

def rollback_group_names(backup_file, auth_token):
    """回滚分组名称到备份时的状态"""
    with open(backup_file, "r", encoding="utf-8") as f:
        backup = json.load(f)

    print(f"开始回滚操作，备份文件：{backup_file}")
    print(f"共有 {len(backup)} 个分组需要处理")
    
    success_count = 0
    error_count = 0

    for old_name, info in backup.items():
        groupid = info['groupid']
        print(f"\n[回滚检查] 原分组名: '{old_name}'，groupid: {groupid}")
        try:
            # 获取当前分组名
            result = call_api("hostgroup.get", {
                "output": ["groupid", "name"],
                "groupids": [groupid]
            }, auth_token)

            if not result:
                print(f"[缺失] 分组ID {groupid} 不存在，尝试重新创建分组 '{old_name}'")
                try:
                    created = call_api("hostgroup.create", {"name": old_name}, auth_token)
                    new_groupid = created['groupids'][0]
                    print(f"[回滚] 已重新创建分组 '{old_name}'，ID: {new_groupid}")
                    logging.info(f"[回滚] 已重新创建分组 '{old_name}'，ID: {new_groupid}")
                    
                    # 使用新的groupid进行主机恢复
                    restore_hosts_to_group(info['hosts'], new_groupid, old_name, auth_token)
                    success_count += 1
                except Exception as e2:
                    print(f"[回滚失败] 分组 '{old_name}'：无法重新创建或关联主机，错误：{str(e2)}")
                    logging.error(f"[回滚失败] 分组 '{old_name}'：无法重新创建或关联主机，错误：{str(e2)}")
                    error_count += 1
                continue

            current_name = result[0]['name']
            print(f"[检查名称] 当前名称：'{current_name}'，目标：'{old_name}'")

            # 无论分组名称是否需要修改，都要恢复主机关联
            restore_hosts_to_group(info['hosts'], groupid, old_name, auth_token)

            if current_name != old_name:
                # 回滚分组名称
                call_api("hostgroup.update", {
                    "groupid": groupid,
                    "name": old_name
                }, auth_token)
                print(f"[回滚成功] 分组 '{current_name}' -> '{old_name}'")
                logging.info(f"[回滚成功] 分组 '{current_name}' -> '{old_name}'")
            else:
                print(f"[已是原名] 分组 '{old_name}' 无需重命名")
            
            success_count += 1

        except Exception as e:
            print(f"[回滚失败] 分组 '{old_name}'：{str(e)}")
            logging.error(f"[回滚失败] 分组 '{old_name}'：{str(e)}")
            error_count += 1
        
        time.sleep(0.1)  # 避免请求过快

    print(f"\n✅ 回滚操作完成！")
    print(f"成功: {success_count} 个分组")
    print(f"失败: {error_count} 个分组")
    if error_count > 0:
        print("详细错误信息请查看 rollback.log 文件")

def restore_hosts_to_group(hosts, target_groupid, group_name, auth_token):
    """恢复主机到指定分组，并从下线分组中移除"""
    if not hosts:
        print(f"[跳过] 分组 '{group_name}' 没有需要恢复的主机")
        return
    
    print(f"[恢复主机] 开始恢复 {len(hosts)} 个主机到分组 '{group_name}'")
    
    # 获取"下线"分组ID
    offline_groups = call_api("hostgroup.get", {
        "filter": {"name": "下线"},
        "output": ["groupid"]
    }, auth_token)
    offline_groupids = {g['groupid'] for g in offline_groups}
    
    for host in hosts:
        hostid = host['hostid']
        hostname = host.get('name', '未知名称')
        try:
            # 获取当前主机关联的所有分组
            host_info = call_api("host.get", {
                "output": ["hostid"],
                "selectGroups": ["groupid"],
                "hostids": hostid
            }, auth_token)

            if host_info:
                existing_groups = host_info[0].get("groups", [])
                group_ids = [g["groupid"] for g in existing_groups]

                # 构造新的分组列表：移除"下线"分组，确保包含目标分组
                new_group_ids = [gid for gid in group_ids if gid not in offline_groupids]
                if target_groupid not in new_group_ids:
                    new_group_ids.append(target_groupid)
                
                # 确保主机至少属于一个分组
                if not new_group_ids:
                    new_group_ids = [target_groupid]

                # 更新主机分组
                call_api("host.update", {
                    "hostid": hostid,
                    "groups": [{"groupid": gid} for gid in new_group_ids]
                }, auth_token)

                print(f"[恢复主机] ID: {hostid}, 名称: {hostname}, 结果: 成功")
                logging.info(f"[恢复主机] ID: {hostid}, 名称: {hostname}, 结果: 成功")
        except Exception as ex:
            print(f"[主机恢复失败] ID: {hostid}, 名称: {hostname}, 错误: {str(ex)}")
            logging.error(f"[主机恢复失败] ID: {hostid}, 名称: {hostname}, 错误: {str(ex)}")

if __name__ == '__main__':
    import glob
    import os
    
    # 自动查找最新的备份文件
    backup_files = glob.glob('group_backup_*.json')
    if not backup_files:
        print("错误：未找到任何备份文件 (group_backup_*.json)")
        exit(1)
    
    # 按修改时间排序，选择最新的
    backup_files.sort(key=os.path.getmtime, reverse=True)
    backup_file = backup_files[0]
    
    print(f"找到 {len(backup_files)} 个备份文件：")
    for i, file in enumerate(backup_files):
        marker = " (最新)" if i == 0 else ""
        print(f"  {i+1}. {file}{marker}")
    
    print(f"\n准备使用备份文件进行回滚：{backup_file}")
    confirm = input("确认要执行回滚操作吗？这将恢复所有分组到备份时的状态 (y/N): ")
    
    if confirm.lower() == 'y':
        token = get_auth_token()
        rollback_group_names(backup_file, token)
    else:
        print("回滚操作已取消")