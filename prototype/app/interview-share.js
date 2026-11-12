(function () {
  'use strict';
  // 인터뷰 초대 링크 보내기 — 초대 주소를 만든 직후 화면(준비한 초대)에 「링크 보내기」를 둔다.
  //  받는 분 이름 · 주제로 인사 글을 미리 채우고, 카카오톡 · 문자 · 이메일 · 복사 중 골라 보낸다.
  //  주소는 기존 규칙대로 만든 직후 한 번만 보인다(이 화면을 떠나면 다시 보이지 않음).
  const share = window.MemoirShare;
  const screen = document.querySelector('[data-screen="invitations"]');
  if (!share || !screen) return;
  const CH = {copy: '복사', kakao: '카카오톡', sms: '문자', mail: '이메일', more: '다른 앱'};

  function invitationOf(address) {
    const store = window.RolePreview.store, inv = store.invitationByAddress(address || '');
    if (!inv) return null;
    const data = store.snapshot();
    return {inv, person: data.elders.find((e) => e.elder_id === inv.elder_id), user: data.user};
  }

  function decorate() {
    const actions = screen.querySelector('.role-issued-actions');
    if (!actions || actions.querySelector('.is-send')) return;
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'button primary is-send';
    b.innerHTML = `${icons('share')}<span>링크 보내기</span>`;
    actions.prepend(b);
    const copy = actions.querySelector('[data-role="copy-address"]');
    if (copy) { copy.classList.remove('primary'); copy.classList.add('outline'); }
    b.addEventListener('click', open);
  }
  new MutationObserver(decorate).observe(screen, {childList: true, subtree: true});

  function open() {
    const address = document.getElementById('issued-address')?.value;
    const found = invitationOf(address);
    const name = found?.person?.name || '이야기 주인공';
    const topic = found?.inv?.topic || '살아온 이야기';
    share.open({
      kind: 'invite', eyebrow: '인터뷰 초대 보내기', title: `${name} 님에게 초대 보내기`,
      card: {kicker: '내말싸미 · 이야기 초대', title: `${name} 님, 이야기를 들려주세요`, sub: `주제 「${topic}」 · 누르면 휴대폰에서 바로 시작해요`, art: `<span class="share-mini-mic">${icons('mic')}</span>`},
      message: `${name}, 안녕하세요. ${name}의 「${topic}」 이야기를 듣고 싶어서 초대 링크를 보내요.\n링크를 누르면 휴대폰에서 바로 시작할 수 있어요. 질문에 답하듯 편하게 말씀해 주시면 돼요.`,
      link: address,
      status: '',
      note: '이 링크는 받는 분 한 분만 쓰도록 만든 초대예요. 다른 사람에게 전달되지 않게 해 주세요. 보낸 뒤에도 「초대 취소」로 막을 수 있어요.',
      extras: [],
      onSent: (how) => {
        const r = document.getElementById('copy-result');
        if (r) r.textContent = how === 'copy' ? '글과 링크를 복사했어요. 받는 분에게 붙여 넣어 보내 주세요.' : `${CH[how]}(으)로 보낼 준비를 했어요. 보낸 뒤 받는 분이 열었는지는 아래 목록에서 볼 수 있어요.`;
      },
    });
  }
  decorate();
  window.MemoirInviteShare = {open};
}());
