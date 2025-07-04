import csv
import json
import requests
import logging
import time
from datetime import datetime

# ====== Zabbix 配置 ======
ZABBIX_URL = 'http://127.0.0.1/api_jsonrpc.php'
USERNAME = 'Admin'
PASSWORD = 'zabbix'

# ====== 日志配置 ======
logging.basicConfig(
    filename='group_update.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ====== 获取认证 Token ======def get_auth_token():
def get_auth_token():
    payload = {
        "jsonrpc": "2.0",
        "method": "user.login",
        "params": {
            "username": USERNAME,
            "password": PASSWORD
        },
        "id": 1
    }
    response = requests.post(ZABBIX_URL, json=payload)

    # 打印响应内容
    print("Zabbix 返回内容：", response.text)

    return response.json()['result']

# ====== 通用 API 请求 ======
def call_api(method, params, auth_token):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}"
    }
    response = requests.post(ZABBIX_URL, json=payload, headers=headers)
    result = response.json()
    if 'error' in result:
        raise Exception(result['error'])
    return result['result']

# ====== 获取所有分组及主机信息并备份（一次性拉取全部） ======
def backup_all_groups_and_hosts(auth_token):
    print("开始备份所有分组和主机信息...")
    all_groups = call_api("hostgroup.get", {
        "output": ["groupid", "name"],
        "selectHosts": ["hostid", "name"]
    }, auth_token)

    backup = {}
    for group in all_groups:
        backup[group['name']] = {
            "groupid": group['groupid'],
            "hosts": group.get('hosts', [])
        }
        print(f"[备份] 分组: {group['name']} (ID: {group['groupid']}), 主机数量: {len(group.get('hosts', []))}")

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_file = f"group_backup_{ts}.json"
    with open(backup_file, "w", encoding="utf-8") as f:
        json.dump(backup, f, ensure_ascii=False, indent=2)

    logging.info(f"[备份完成] 文件：{backup_file}")
    print(f"备份完成，保存文件: {backup_file}")
    return backup_file

# ====== 修改分组名 ======
def rename_group(original_name, new_name, auth_token):
    try:
        # 定义可能的前缀列表
        prefixes = ['a_', 'b_', 'c_', 'd_', 'e_', 'f_', 'g_', 'h_', 'i_', 'j_', 'k_', 'l_', 'm_', 'n_', 'o_', 'p_', 'q_', 'r_', 's_', 't_', 'u_', 'v_', 'w_', 'x_', 'y_', 'z_']
        
        # 首先尝试精确匹配原名称
        result = call_api("hostgroup.get", {
            "filter": {"name": original_name},
            "output": ["groupid", "name"],
            "selectHosts": ["hostid"]
        }, auth_token)
        
        # 如果精确匹配失败，尝试带前缀的匹配
        if not result:
            for prefix in prefixes:
                prefixed_name = prefix + original_name
                result = call_api("hostgroup.get", {
                    "filter": {"name": prefixed_name},
                    "output": ["groupid", "name"],
                    "selectHosts": ["hostid"]
                }, auth_token)
                if result:
                    print(f"[找到匹配] 使用前缀 '{prefix}' 找到分组：{prefixed_name}")
                    logging.info(f"[找到匹配] 使用前缀 '{prefix}' 找到分组：{prefixed_name}")
                    break
        
        if not result:
            logging.warning(f"[未找到] 原分组：{original_name}（已尝试所有前缀）")
            print(f"[未找到] 原分组：{original_name}（已尝试所有前缀）")
            return None
        elif len(result) > 1:
            match_names = [g['name'] for g in result]
            logging.warning(f"[匹配多个分组] 原分组：{original_name} 匹配到多个：{match_names}")
            print(f"[匹配多个分组] 原分组：{original_name} 匹配到多个：{match_names}")
            return None

        group = result[0]
        groupid = group['groupid']
        old_name = group['name']
        hostids = [h['hostid'] for h in group.get('hosts', [])]

        if new_name == '下线':
            move_hosts_to_group(hostids, '下线', auth_token)
            print(f"[迁移] 将分组 '{old_name}' 中 {len(hostids)} 个主机移动到 '下线'")
            logging.info(f"[迁移] 将分组 '{old_name}' 中 {len(hostids)} 个主机移动到 '下线'")
            # 返回原群组ID，用于后续清理
            return groupid

        # 正常重命名逻辑，保留前缀
        final_new_name = new_name
        if '_' in old_name:
            prefix = old_name.split('_')[0] + '_'
            if not new_name.startswith(prefix):
                final_new_name = prefix + new_name
                print(f"[保留前缀] 为新名称添加前缀：{new_name} -> {final_new_name}")
                logging.info(f"[保留前缀] 为新名称添加前缀：{new_name} -> {final_new_name}")

        call_api("hostgroup.update", {
            "groupid": groupid,
            "name": final_new_name
        }, auth_token)
        logging.info(f"[成功] 分组 '{old_name}' 重命名为 '{final_new_name}'")
        print(f"[成功] 分组 '{old_name}' 重命名为 '{final_new_name}'")
        return None  # 重命名操作不需要清理

    except Exception as e:
        logging.error(f"[失败] 分组 '{original_name}' 重命名为 '{new_name}' 出错：{str(e)}")
        print(f"[失败] 分组 '{original_name}' 重命名为 '{new_name}' 出错：{str(e)}")
        return None


# 将主机移动到指定分组（替换原有分组）
def move_hosts_to_group(hostids, target_group_name, auth_token):
    if not hostids:
        return

    # 获取目标分组ID（不存在则创建）
    groups = call_api("hostgroup.get", {
        "filter": {"name": target_group_name},
        "output": ["groupid"]
    }, auth_token)

    if groups:
        target_groupid = groups[0]['groupid']
    else:
        created = call_api("hostgroup.create", {"name": target_group_name}, auth_token)
        target_groupid = created['groupids'][0]

    for hostid in hostids:
        call_api("host.update", {
            "hostid": hostid,
            "groups": [{"groupid": target_groupid}]
        }, auth_token)

# ====== 检查群组是否为空 ======
def is_group_empty(groupid, auth_token):
    """检查指定群组是否为空（没有主机）"""
    try:
        # 确保 groupid 是有效的数字
        if groupid is None:
            logging.error(f"[检查群组] groupid 为 None")
            return False
        
        # 转换为整数，如果失败则记录错误
        try:
            groupid_int = int(groupid)
        except (ValueError, TypeError) as e:
            logging.error(f"[检查群组] 无法将 groupid '{groupid}' 转换为整数: {str(e)}")
            return False
            
        result = call_api("host.get", {
            "output": ["hostid"],
            "groupids": [groupid_int],
            "limit": 1
        }, auth_token)
        return len(result) == 0
    except Exception as e:
        logging.error(f"[检查群组] 检查群组 {groupid} 是否为空时出错：{str(e)}")
        return False

# ====== 删除空的主机群组 ======
def delete_empty_group(groupid, group_name, auth_token):
    """删除空的主机群组"""
    try:
        # 确保 groupid 是有效的数字
        if groupid is None:
            logging.error(f"[删除群组] groupid 为 None，群组名: {group_name}")
            return False
        
        # 转换为整数，如果失败则记录错误
        try:
            groupid_int = int(groupid)
        except (ValueError, TypeError) as e:
            logging.error(f"[删除群组] 无法将 groupid '{groupid}' 转换为整数: {str(e)}，群组名: {group_name}")
            return False
            
        if not is_group_empty(groupid, auth_token):
            print(f"[跳过删除] 群组 '{group_name}' 不为空，跳过删除")
            logging.warning(f"[跳过删除] 群组 '{group_name}' 不为空，跳过删除")
            return False
        
        # 修复：使用正确的API参数格式
        call_api("hostgroup.delete", [str(groupid_int)], auth_token)
        
        print(f"[删除成功] 空群组 '{group_name}' 已删除")
        logging.info(f"[删除成功] 空群组 '{group_name}' 已删除")
        return True
        
    except Exception as e:
        print(f"[删除失败] 群组 '{group_name}' 删除失败：{str(e)}")
        logging.error(f"[删除失败] 群组 '{group_name}' 删除失败：{str(e)}")
        return False

# ====== 批量清理空群组 ======
def cleanup_empty_groups(group_ids_to_check, auth_token):
    """批量清理空的主机群组"""
    if not group_ids_to_check:
        return 0
    
    print(f"开始检查并清理 {len(group_ids_to_check)} 个可能为空的群组...")
    deleted_count = 0
    
    for groupid in group_ids_to_check:
        try:
            # 确保 groupid 是有效的数字
            if groupid is None:
                logging.error(f"[清理群组] groupid 为 None，跳过")
                continue
            
            # 转换为整数，如果失败则记录错误并跳过
            try:
                groupid_int = int(groupid)
            except (ValueError, TypeError) as e:
                logging.error(f"[清理群组] 无法将 groupid '{groupid}' 转换为整数: {str(e)}，跳过")
                continue
                
            # 获取群组信息
            group_info = call_api("hostgroup.get", {
                "output": ["groupid", "name"],
                "groupids": [groupid_int]
            }, auth_token)
            
            if not group_info:
                logging.warning(f"[清理群组] 群组 {groupid} 不存在，跳过")
                continue
                
            group_name = group_info[0]['name']
            
            if delete_empty_group(groupid, group_name, auth_token):
                deleted_count += 1
                
        except Exception as e:
            logging.error(f"[清理群组] 处理群组 {groupid} 时出错：{str(e)}")
    
    if deleted_count > 0:
        print(f"✅ 清理完成，共删除 {deleted_count} 个空群组")
        logging.info(f"清理完成，共删除 {deleted_count} 个空群组")
    else:
        print("没有空群组需要删除")
    
    return deleted_count

# ====== 主程序入口 ======
def main():
    auth_token = get_auth_token()
    csv_file = 'group_changes.csv'

    # 读取 CSV 并打印调试信息
    all_orig_names = set()
    rows = []
    groups_to_cleanup = set()  # 用于收集需要清理的群组ID

    with open(csv_file, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        print("读取 CSV 文件头字段：", reader.fieldnames)
        for row in reader:
            print(f"读取行数据：{row}")
            # 添加空值检查
            new_name_raw = row['修改后系统名称']
            if new_name_raw is None or new_name_raw.strip() == '':
                print(f"跳过空值行：{row}")
                continue
            new_name = new_name_raw.strip()
            if new_name == '无需修改':
                continue
            
            orig_name = row['原系统名称'].strip()
            if not orig_name:
                continue
                
            # 直接使用CSV中的原系统名称，让rename_group函数去处理前缀匹配
            all_orig_names.add(orig_name)
            rows.append(([orig_name], new_name))

    # === 步骤1：备份，改为全量备份 ===
    backup_file = backup_all_groups_and_hosts(auth_token)

    # === 步骤2：重命名并收集需要清理的群组 ===
    total = len(rows)
    count = 0
    for orig_names, new_name in rows:
        count += 1
        print(f"正在处理第 {count}/{total} 条记录，目标名称：'{new_name}'，原系统名称列表：{orig_names}")
        for orig_name in orig_names:
            print(f"  正在修改分组：'{orig_name}' -> '{new_name}'")
            # 如果是下线操作，收集原群组ID用于后续清理
            original_groupid = rename_group(orig_name, new_name, auth_token)
            if original_groupid and new_name == '下线':
                groups_to_cleanup.add(original_groupid)
            time.sleep(0.1)  # 延时 0.1 秒，避免过快请求

    # === 步骤3：清理空的主机群组 ===
    if groups_to_cleanup:
        print("\n开始清理空的主机群组...")
        cleanup_empty_groups(list(groups_to_cleanup), auth_token)
    else:
        print("\n没有需要清理的群组")

    print(f"✅ 所有操作完成，备份文件：{backup_file}")

if __name__ == '__main__':
    main()



# # ====== 回滚分组名称 ======ƒ
# def rollback_group_names(backup_file, auth_token):
#     with open(backup_file, "r", encoding="utf-8") as f:
#         backup = json.load(f)

#     for old_name, info in backup.items():
#         groupid = info['groupid']
#         print(f"[回滚检查] 原分组名: '{old_name}'，groupid: {groupid}")
#         try:
#             # 获取当前分组名
#             result = call_api("hostgroup.get", {
#                 "output": ["groupid", "name"],
#                 "groupids": [groupid]
#             }, auth_token)

#             print(f"[API响应] hostgroup.get 返回：{result}")

#             if not result:
#                 print(f"[缺失] 分组ID {groupid} 不存在，尝试重新创建分组 '{old_name}'")
#                 try:
#                     created = call_api("hostgroup.create", {"name": old_name}, auth_token)
#                     new_groupid = created['groupids'][0]
#                     print(f"[回滚] 已重新创建分组 '{old_name}'，ID: {new_groupid}")
#                     logging.info(f"[回滚] 已重新创建分组 '{old_name}'，ID: {new_groupid}")

#                     hostids = [h['hostid'] for h in info['hosts']]
#                     for host in info['hosts']:
#                         hostid = host['hostid']
#                         hostname = host.get('name', '未知名称')
#                         try:
#                             # 获取当前主机关联的所有分组
#                             host_info = call_api("host.get", {
#                                 "output": ["hostid"],
#                                 "selectGroups": ["groupid"],
#                                 "hostids": hostid
#                             }, auth_token)

#                             existing_groups = host_info[0].get("groups", [])
#                             group_ids = [g["groupid"] for g in existing_groups]

#                             # 移除“下线”分组
#                             offline_groups = call_api("hostgroup.get", {
#                                 "filter": {"name": "下线"},
#                                 "output": ["groupid"]
#                             }, auth_token)
#                             offline_groupids = {g['groupid'] for g in offline_groups}

#                             # 构造新的分组列表，去掉“下线”，加入原分组
#                             new_group_ids = [gid for gid in group_ids if gid not in offline_groupids]
#                             if new_groupid not in new_group_ids:
#                                 new_group_ids.append(new_groupid)

#                             # 更新主机分组（去掉“下线”，加上原分组）
#                             call_api("host.update", {
#                                 "hostid": hostid,
#                                 "groups": [{"groupid": gid} for gid in new_group_ids]
#                             }, auth_token)

#                             print(f"[回滚主机] ID: {hostid}, 名称: {hostname}, 结果: 成功")
#                             logging.info(f"[回滚主机] ID: {hostid}, 名称: {hostname}, 结果: 成功")
#                         except Exception as ex:
#                             print(f"[主机回滚失败] ID: {hostid}, 名称: {hostname}, 错误: {str(ex)}")
#                             logging.error(f"[主机回滚失败] ID: {hostid}, 名称: {hostname}, 错误: {str(ex)}")
#                     print(f"[回滚] 已将 {len(hostids)} 个主机重新关联到 '{old_name}'")
#                     logging.info(f"[回滚] 已将 {len(hostids)} 个主机重新关联到 '{old_name}'")
#                 except Exception as e2:
#                     print(f"[回滚失败] 分组 '{old_name}'：无法重新创建或关联主机，错误：{str(e2)}")
#                     logging.error(f"[回滚失败] 分组 '{old_name}'：无法重新创建或关联主机，错误：{str(e2)}")
#                 continue

#             current_name = result[0]['name']
#             print(f"[检查名称] 当前名称：'{current_name}'，目标：'{old_name}'")

#             if current_name == old_name:
#                 print(f"[已是原名] 分组 '{old_name}' 无需回滚")
#                 continue

#             call_api("hostgroup.update", {
#                 "groupid": groupid,
#                 "name": old_name
#             }, auth_token)
#             print(f"[回滚成功] 分组 '{current_name}' -> '{old_name}'")
#             logging.info(f"[回滚成功] 分组 '{current_name}' -> '{old_name}'")

#         except Exception as e:
#             print(f"[回滚失败] 分组 '{old_name}'：{str(e)}")
#             logging.error(f"[回滚失败] 分组 '{old_name}'：{str(e)}")


# # ====== 如果需要执行回滚，取消注释并指定备份文件名 ======
# if __name__ == '__main__':
#     token = get_auth_token()
#     rollback_group_names('group_backup_20250701_160856.json', token)