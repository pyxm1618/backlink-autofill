import { describe, expect, it } from 'vitest'
import { parseSheetTargets } from './sheets'

describe('parseSheetTargets', () => {
  it('maps the BacklinkOS 免费外链机会 headers deterministically', () => {
    const values = [
      ['排名', '优先级', '外链来源域名', '免费情况', '置信度', '机会类型', '提交/入口地址', '核验说明'],
      ['1', 'A', 'promoteproject.com', '免费', '高', '目录站 / 社区', 'https://www.promoteproject.com/', '存在免费的项目推广入口。'],
    ]
    expect(parseSheetTargets(values)).toEqual([
      {
        name: 'promoteproject.com',
        submitUrl: 'https://www.promoteproject.com/',
        priority: 'A',
        type: '目录站 / 社区',
        confidence: '高',
        notes: '存在免费的项目推广入口。',
      },
    ])
  })

  it('accepts the 已确认免费Follow submit header and skips rows without a URL', () => {
    const values = [
      ['域名', '提交/发布入口', '置信度', '备注'],
      ['sideprojects.net', 'https://sideprojects.net/projects', '高', '已确认'],
      ['missing.example', '', '高', 'no route'],
    ]
    expect(parseSheetTargets(values).map((target) => target.name)).toEqual(['sideprojects.net'])
  })

  it('maps the 严格免费外链 condition column into notes', () => {
    const values = [
      ['域名', '获取方式', '提交/发布入口', '条件/备注'],
      ['uneed.best', '免费（条件）', 'https://www.uneed.best/', '当日需 ≥10 upvotes，达标后保持 Dofollow'],
    ]
    expect(parseSheetTargets(values)).toEqual([
      {
        name: 'uneed.best',
        submitUrl: 'https://www.uneed.best/',
        type: '免费（条件）',
        notes: '当日需 ≥10 upvotes，达标后保持 Dofollow',
      },
    ])
  })
})
