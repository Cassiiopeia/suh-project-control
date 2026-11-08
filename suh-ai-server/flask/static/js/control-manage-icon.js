/* 관제소 프로젝트 카드 머리의 썸네일: 미리보기 + 이미지 변경(파일) + 주소로 가져오기 + 삭제
   PUT·DELETE /control/projects/{id}/icon > 성공 시 ControlManage.reload() / window.ControlManageIcon 으로 노출 */
(function () {
  const actions = window.ControlManageActions;
  const createElement = window.ControlFormat.createElement;
  // 파일은 브라우저에서 한 변 256px 정사각 PNG로 줄여 올림 (서버가 128px WebP로 다시 맞춤)
  const UPLOAD_SIDE_PIXELS = 256;
  const ACCEPTED_FILE_TYPES = 'image/png,image/jpeg,image/webp,image/gif,image/x-icon,.ico';
  const URL_PROMPT_TEXT = '가져올 이미지 주소 (https://...)\n사설망 주소는 가져올 수 없습니다.';
  const DELETE_CONFIRM_TEXT = '썸네일을 삭제할까요? 공개 페이지에는 이름 첫 글자 타일이 표시됩니다.';

  // 요청 1건: 실패 안내 > 성공 문구 > 목록 재조회
  async function requestIcon(method, projectId, payload, successMessage) {
    try {
      const result = await actions.sendJson(method, '/projects/' + encodeURIComponent(projectId) + '/icon', payload);
      if (!result.ok) { showToast(actions.describeFailure(result), 'error'); return false; }
      showToast(successMessage, 'success');
      if (window.ControlManage) window.ControlManage.reload();
      return true;
    } catch (error) {
      console.warn('control icon request failed:', error);
      showToast('요청에 실패했습니다', 'error');
      return false;
    }
  }

  // 파일 > 가운데를 잘라 정사각 256px PNG > base64 (data: 접두사 제외)
  function resizeFileToBase64(file) {
    return new Promise(function (resolve, reject) {
      const objectUrl = URL.createObjectURL(file);
      const image = new Image();
      image.onload = function () {
        const canvas = document.createElement('canvas');
        canvas.width = UPLOAD_SIDE_PIXELS;
        canvas.height = UPLOAD_SIDE_PIXELS;
        const shortSide = Math.min(image.naturalWidth, image.naturalHeight);
        const sourceX = (image.naturalWidth - shortSide) / 2;
        const sourceY = (image.naturalHeight - shortSide) / 2;
        canvas.getContext('2d').drawImage(image, sourceX, sourceY, shortSide, shortSide, 0, 0, UPLOAD_SIDE_PIXELS, UPLOAD_SIDE_PIXELS);
        URL.revokeObjectURL(objectUrl);
        resolve(canvas.toDataURL('image/png').split(',')[1]);
      };
      image.onerror = function () { URL.revokeObjectURL(objectUrl); reject(new Error('decode failed')); };
      image.src = objectUrl;
    });
  }

  async function uploadFile(projectId, file) {
    let imageBase64;
    try {
      imageBase64 = await resizeFileToBase64(file);
    } catch (error) {
      showToast('이미지를 읽을 수 없습니다 (PNG·JPEG·WebP·GIF·ICO)', 'error');
      return;
    }
    await requestIcon('PUT', projectId, { image_base64: imageBase64 }, '썸네일을 저장했습니다');
  }

  function createButton(iconName, labelText, extraClass, onClick) {
    const button = createElement('button', 'btn btn-xs ' + extraClass);
    button.type = 'button';
    button.title = labelText;
    const icon = createElement('i', 'size-4');
    icon.setAttribute('data-lucide', iconName);
    button.appendChild(icon);
    button.appendChild(createElement('span', '', labelText));
    button.addEventListener('click', onClick);
    return button;
  }

  // 미리보기: 썸네일 있으면 이미지, 없으면 이름 첫 글자 타일
  function createPreview(project) {
    if (project.icon_data_url) {
      const image = createElement('img', 'size-10 rounded-lg object-cover border border-base-300');
      image.src = project.icon_data_url;
      image.alt = project.name + ' 썸네일';
      return image;
    }
    const tile = createElement('span', 'size-10 rounded-lg bg-base-200 border border-base-300 flex items-center justify-center font-semibold opacity-70',
      Array.from(project.name)[0] || '?');
    tile.title = '썸네일 없음';
    return tile;
  }

  function createIconControl(project) {
    const group = createElement('div', 'flex items-center gap-2');
    group.appendChild(createPreview(project));

    const fileInput = createElement('input', 'hidden');
    fileInput.type = 'file';
    fileInput.accept = ACCEPTED_FILE_TYPES;
    fileInput.setAttribute('aria-label', project.name + ' 썸네일 파일');
    fileInput.addEventListener('change', async function () {
      const file = fileInput.files[0];
      fileInput.value = '';
      if (file) await uploadFile(project.id, file);
    });
    group.appendChild(fileInput);

    group.appendChild(createButton('image-up', '이미지', 'btn-outline', function () { fileInput.click(); }));
    group.appendChild(createButton('link', '주소', 'btn-outline', async function () {
      const sourceUrl = window.prompt(URL_PROMPT_TEXT, project.icon_source_url || 'https://');
      if (sourceUrl && sourceUrl.trim()) {
        await requestIcon('PUT', project.id, { source_url: sourceUrl.trim() }, '이미지를 가져와 저장했습니다');
      }
    }));
    if (project.icon_data_url) {
      group.appendChild(createButton('trash-2', '삭제', 'btn-ghost', function () {
        if (confirm(DELETE_CONFIRM_TEXT)) requestIcon('DELETE', project.id, undefined, '썸네일을 삭제했습니다');
      }));
    }
    return group;
  }

  window.ControlManageIcon = { createIconControl: createIconControl };
})();
