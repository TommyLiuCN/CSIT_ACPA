# for循环乘法表
# for i in range(1, 10):
#     for j in range(1, i + 1):
#         print(
#             f"{j}*{i}={i * j}",end="\t")
#     print()
# for i in range(2, 100):
#     is_prime = 1
#     end = int(i**0.5)
#     for j in range(2, end + 1):
#         if i % j == 0:
#             is_prime = 0
#             break
#     if is_prime:
#         print(i)
# import random

# money = 1000
# while money > 0:
#     print(f"你的总资产为: {money}元")
#     # 下注金额必须大于0且小于等于玩家的总资产
#     while True:
#         debt = int(input("请下注: "))
#         if 0 < debt <= money:
#             break
#     # 用两个1到6均匀分布的随机数相加模拟摇两颗色子得到的点数
#     first_point = random.randrange(1, 7) + random.randrange(1, 7)
#     print(f"\n玩家摇出了{first_point}点")
#     if first_point == 7 or first_point == 11:
#         print("玩家胜!\n")
#         money += debt
#     elif first_point == 2 or first_point == 3 or first_point == 12:
#         print("庄家胜!\n")
#         money -= debt
#     else:
#         # 如果第一次摇色子没有分出胜负，玩家需要重新摇色子
#         while True:
#             current_point = random.randrange(1, 7) + random.randrange(1, 7)
#             print(f"玩家摇出了{current_point}点")
#             if current_point == 7:
#                 print("庄家胜!\n")
#                 money -= debt
#                 break
#             elif current_point == first_point:
#                 print("玩家胜!\n")
#                 money += debt
#                 break
# print("你破产了, 游戏结束!")
# import random

# counters = [0] * 6
# total_rolls = 6000  # 把总次数提取成一个变量，方便后面计算

# # 模拟掷色子
# for _ in range(total_rolls):
#     face = random.randrange(1, 7)
#     counters[face - 1] += 1

# # 输出次数和概率
# print(f"总投掷次数：{total_rolls}")
# for face in range(1, 7):
#     count = counters[face - 1]
#     # 用单斜杠 / 进行除法，然后用 f-string 的 .2f 保留两位小数
#     probability = (count / total_rolls) * 100
#     print(f"{face}点出现了 {count} 次，概率约为 {probability:.2f}%")
