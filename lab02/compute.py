def c(n: int, k: int):
    prod = 1
    for i in range(k):
        prod *= n - i
    for i in range(k):
        prod /= i + 1
    return int(prod)

def prob(n: int, k: int, p: float):
    return c(n, k) * p**k * (1 - p)**(n - k)

less_than_12 = 0
for i in range(12):
    less_than_12 += prob(60, i, 0.2)

print(1 - less_than_12) # 55.13%