/** 空着的时候给她点一下试试的。挑的是最常见、也最能看出「认得准」的四种 */
export const EXAMPLES: { label: string; text: string }[] = [
  {
    label: '一段群聊',
    text: `王总：下周三之前能把方案初稿给到吗？
Lily：可以，但数据那块要等财务给口径
王总：财务那边我去催
张三：我这边竞品分析周一能出
Lily：好的，那我周二先出一版框架，周三合稿
王总：行，周三下午碰一下`,
  },
  {
    label: '一封英文邮件',
    text: `Hi,

Thanks for the deck yesterday. The team liked the segmentation work, but we're not convinced about the pricing tiers — the mid tier feels too close to premium. Could you share the underlying willingness-to-pay data before our Friday call?

Best,
Sarah`,
  },
  {
    label: '一段报错',
    text: `Traceback (most recent call last):
  File "/app/run_pipeline.py", line 42, in <module>
    main()
  File "/app/run_pipeline.py", line 37, in main
    rows = fetch(cfg["source"])
KeyError: 'source'`,
  },
  {
    label: '一串问题',
    text: `1. 国内头部电商的会员体系，付费会员渗透率大概是多少？
2. 付费会员对复购的提升有多少，有没有公开的数据？
3. 积分体系和付费会员同时存在时，用户会不会混淆？`,
  },
]
