'use strict';
const fs = require('node:fs');
const path = require('node:path');
const sourceDir = process.argv[2];
if (!sourceDir) throw new Error('Pass the directory containing the three captured JPEGs.');
const cards = [
  ['01', 'LifeLog', '공개 첫 화면 · 실제 캡처', 'design-01-lifelog.jpg', '종이색 · 명조 · 책과 추억', '책으로 완성되는 결과를 먼저 보여주는 구성'],
  ['02', '내말싸미 현재', '기존 홈 화면 · 실제 캡처', 'design-02-current.jpg', '아이보리 · 버건디 · 펼친 책', '책과 사진이 중심인 현재의 첫인상'],
  ['03', '내말싸미 제안', '디자인 예시 · 실제 홈 미반영', 'design-03-proposal.jpg', '질문 · 라디오 · 기억 엽서', '말로 시작하는 경험과 한 장씩 남기는 기록을 강조'],
];
const figures = cards.map(([number,title,label,file,theme,description]) => {
  const image = fs.readFileSync(path.join(sourceDir,file)).toString('base64');
  return `<figure><header><span class="number">${number}</span><div><h2>${title}</h2><p>${label}</p></div></header><div class="capture"><img src="data:image/jpeg;base64,${image}" alt="${title} ${label}"></div><figcaption><h3>${theme}</h3><p>${description}</p></figcaption></figure>`;
}).join('');
const html = `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>내말싸미 · 디자인 3종 비교</title><style>
*{box-sizing:border-box}body{margin:0;color:#252c2b;background:#f1f3f1;font-family:"Malgun Gothic","Apple SD Gothic Neo",sans-serif}.board{width:2400px;padding:56px 48px 44px} .intro{display:flex;align-items:flex-end;justify-content:space-between;gap:40px;margin-bottom:36px}.intro h1{margin:0 0 12px;font-size:42px;letter-spacing:-1.8px}.intro p{margin:0;font-size:23px;color:#626b66;line-height:1.6}.intro .scope{text-align:right;font-size:19px}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:28px}figure{margin:0;background:#fff;border:1px solid #d9dfda;border-radius:14px;overflow:hidden}header{display:flex;align-items:center;gap:18px;padding:26px 26px 24px}.number{color:#7c8a82;font-size:22px;font-weight:600}h2{margin:0 0 8px;font-size:30px;letter-spacing:-1px}header p{margin:0;color:#68756d;font-size:18px}.capture{border-block:1px solid #e5e9e5;background:#fafbf9}img{display:block;width:100%;height:auto}figcaption{padding:26px}h3{margin:0 0 12px;font-size:25px;letter-spacing:-.7px}figcaption p{margin:0;font-size:19px;line-height:1.7;color:#5c6962}.foot{margin:26px 0 0;color:#69736d;font-size:18px;line-height:1.7}.grid figure:last-child{border-color:#8da99a}.grid figure:last-child .number{color:#335f4f}
@media(max-width:2399px){.board{width:100%;padding:30px 24px 24px}.intro{margin-bottom:24px}.intro h1{font-size:30px;margin-bottom:8px}.intro p{font-size:17px}.intro .scope{font-size:13px}.grid{gap:20px}header{padding:20px;gap:12px}.number{font-size:17px}h2{font-size:23px}header p{font-size:13px}figcaption{padding:20px}h3{font-size:19px;margin-bottom:8px}figcaption p{font-size:14px}.foot{font-size:12px;margin-top:18px}}
</style></head><body><main class="board"><div class="intro"><div><h1>첫 화면의 인상을 어떻게 구별할까</h1><p>경쟁사 · 현재 시안 · 변경 제안의 세 가지 이미지</p></div><p class="scope">01·02 실제 화면 / 03 검토용 예시<br>기능 추가와 브랜드 변경은 현재 홈에 반영하지 않았습니다.</p></div><div class="grid">${figures}</div><p class="foot">비교 범위: LifeLog 공개 소개 첫 화면과 내말싸미 홈의 시각적 인상. 회원용 전체 화면이나 동일한 사용 단계의 기능 비교를 뜻하지 않습니다. · 2026. 11. 09.</p></main></body></html>`;
fs.writeFileSync(path.join(__dirname,'comparison.html'),html);
console.log('Wrote design-comparison/comparison.html using three actual capture files.');
