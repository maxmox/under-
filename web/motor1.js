// Motor 1 — empírico. Espelho linha a linha de motor1.py (a referência).
// testes/test_paridade.py roda este arquivo num motor JS e confere que as duas
// versões dão o mesmo número. Mudou a lógica aqui? Mude lá também.
//
// Responde: "jogos históricos que estavam exatamente nesta situação — mesmo
// minuto, mesmo placar em relação ao favorito, favoritismo parecido — em
// quantos % o placar NÃO mudou até o fim do período?" (= green do under limite)
//
// Convenções (idênticas às do Python):
//  * instante t = M - 1: o minuto em andamento conta como FUTURO (conservador)
//  * M <= 45 é 1º tempo; M >= 46 é 2º; 'HT' é o início do 2º (t = 45)
//  * favorito = maior probabilidade 1X2 sem margem (empate -> casa)
(function (raiz) {
  'use strict';

  const N_MIN = 100;
  const Z = 1.96;

  // [janela_fav, janela_over, usa_alvo, usa_chutes] — degrau cujo filtro não
  // pode ser aplicado vira cópia do seguinte e é pulado; o rótulo sai dos
  // filtros EFETIVAMENTE aplicados
  const ESCADA = [
    [0.03, 0.04, true, true],
    [0.03, 0.04, true, false],
    [0.03, 0.04, false, false],
    [0.05, 0.07, false, false],
    [0.05, null, false, false],
    [0.08, null, false, false],
    [0.12, null, false, false],
    [null, null, false, false],
  ];

  function rotulo(jf, jo, usaA, usaC) {
    const partes = [];
    if (jf !== null) partes.push(('fav ±' + jf.toFixed(2)).replace('.', ','));
    if (jo !== null) partes.push(('O/U ±' + jo.toFixed(2)).replace('.', ','));
    if (usaA) partes.push('no alvo');
    if (usaC) partes.push('chutes');
    return partes.join(' · ') || 'só minuto e placar';
  }

  const SEM_BASE = {
    xg: 'xG do Fut Odds e de outro modelo que o do historico',
    xgs: 'sem equivalente no historico',
    pi1: 'sem equivalente no historico', pi2: 'sem equivalente no historico',
    pi3: 'sem equivalente no historico',
    appm: 'sem equivalente no historico', appm10: 'sem equivalente no historico',
    cg: 'sem equivalente no historico', cg10: 'sem equivalente no historico',
    canto: 'historico so tem o total do jogo, sem minuto',
    ataq: 'sem equivalente no historico', aper: 'sem equivalente no historico',
    poss: 'historico so tem agregado final',
    amar: 'historico sem cartoes', h2h: 'sem equivalente no historico',
  };

  let jogos = null, ligas = null;

  function decodifica(cod) {
    const tempo = Math.floor(cod / 10000);
    const resto = cod % 10000;
    return [tempo, Math.floor(resto / 10), Math.floor((resto % 10) / 2), resto % 2];
  }

  function tolerancia(x) { return Math.max(1, Math.floor(0.25 * x + 0.5)); }

  function wilson(v, n) {
    if (n === 0) return [0, 1];
    const p = v / n;
    const den = 1 + Z * Z / n;
    const centro = (p + Z * Z / (2 * n)) / den;
    const meia = Z * Math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / den;
    return [Math.max(0, centro - meia), Math.min(1, centro + meia)];
  }

  function semMargem(...odds) {
    const inv = odds.map(o => 1 / o);
    const s = inv.reduce((a, b) => a + b, 0);
    return inv.map(x => x / s);
  }

  function soma(par) {
    if (!par) return null;
    const [a, b] = par;
    if ((a === null || a === undefined) && (b === null || b === undefined)) return null;
    return (a || 0) + (b || 0);
  }

  function preenchido(v) {
    if (Array.isArray(v)) return soma(v) !== null;
    return v !== null && v !== undefined;
  }

  function instante(jogo) {
    if (jogo.noIntervalo) return [2, 45];
    const m = parseInt(jogo.minuto || 0, 10);
    if (m <= 45) return [1, Math.max(0, m - 1)];
    return [2, m - 1];
  }

  function carregarDoc(doc) {
    ligas = doc.ligas;
    jogos = doc.jogos.map(([liga, temp, pc, pe, pf, po, evs]) => ({
      liga, temporada: temp,
      fav: pc >= pf ? 0 : 1,
      pfav: Math.max(pc, pf) / 1000,
      po: po >= 0 ? po / 1000 : null,
      ev: evs.map(decodifica),
    }));
    return jogos.length;
  }

  function estado(ev, tempoAtual, t) {
    const gols = [0, 0];
    let alvo = 0, chutes = 0, futHt = 0, futFt = 0;
    for (const [tempo, minuto, tipo, lado] of ev) {
      const passado = tempo < tempoAtual || (tempo === tempoAtual && minuto < t);
      const ehGol = tipo === 0 || tipo === 3;
      if (passado) {
        if (ehGol) gols[lado] += 1;
        if (tipo <= 1) alvo += 1;
        if (tipo <= 2) chutes += 1;
      } else if (ehGol) {
        futFt += 1;
        if (tempo === 1) futHt += 1;
      }
    }
    return [gols, alvo, chutes, futHt, futFt];
  }

  function consulta(jogo, periodo, nMin) {
    if (!jogos) return { ok: false, motivo: 'base historica nao carregada' };
    nMin = nMin || N_MIN;
    const [tempoAtual, t] = instante(jogo);
    if (periodo === 'ht' && tempoAtual !== 1) return { ok: false, motivo: '1o tempo ja terminou' };

    const avisos = [], ignorados = [];
    const oc = jogo.ocasa, oe = jogo.oempa, of = jogo.ofora;
    let favVivo, pfavVivo;
    if (oc && oe && of && Math.min(oc, oe, of) > 1) {
      const [pc, , pf] = semMargem(oc, oe, of);
      favVivo = pc >= pf ? 0 : 1;
      pfavVivo = Math.max(pc, pf);
    } else {
      favVivo = 0; pfavVivo = null;
      avisos.push('sem odds 1X2: placar lido como casa x fora e sem filtro de favoritismo');
    }

    const ov = jogo.ov25, un = jogo.un25;
    const poVivo = (ov && un && ov > 1 && un > 1) ? semMargem(ov, un)[0] : null;

    const golsVivo = [parseInt(jogo.golsC || 0, 10), parseInt(jogo.golsF || 0, 10)];
    const gfVivo = golsVivo[favVivo], gzVivo = golsVivo[1 - favVivo];
    const alvoVivo = soma(jogo.cag);
    const chutesVivo = soma(jogo.chut);

    if (soma(jogo.verm)) avisos.push('expulsao no jogo: o historico nao tem cartoes, a taxa NAO considera a expulsao');
    for (const [campo, motivo] of Object.entries(SEM_BASE))
      if (preenchido(jogo[campo])) ignorados.push(campo + ': ' + motivo);

    const cands = [];
    for (const jh of jogos) {
      const [gols, alvo, chutes, futHt, futFt] = estado(jh.ev, tempoAtual, t);
      const fav = pfavVivo !== null ? jh.fav : 0;
      if (gols[fav] !== gfVivo || gols[1 - fav] !== gzVivo) continue;
      cands.push([jh.pfav, jh.po, alvo, chutes, periodo === 'ht' ? futHt : futFt]);
    }

    let escolha = null;
    const vistos = new Set();
    for (let nivel = 0; nivel < ESCADA.length; nivel++) {
      const [jf, jo, ua, uc] = ESCADA[nivel];
      if (pfavVivo === null && jf !== null) continue;
      const joEf = (jo !== null && poVivo !== null) ? jo : null;
      const usaA = ua && alvoVivo !== null;
      const usaC = uc && chutesVivo !== null;
      const assin = [jf, joEf, usaA, usaC].join('|');
      if (vistos.has(assin)) continue;
      vistos.add(assin);
      const rot = rotulo(jf, joEf, usaA, usaC);
      const sel = [];
      for (const [pfav, po, alvo, chutes, futuro] of cands) {
        if (jf !== null && Math.abs(pfav - pfavVivo) > jf + 1e-9) continue;
        if (joEf !== null && (po === null || Math.abs(po - poVivo) > joEf + 1e-9)) continue;
        if (usaA && Math.abs(alvo - alvoVivo) > tolerancia(alvoVivo)) continue;
        if (usaC && Math.abs(chutes - chutesVivo) > tolerancia(chutesVivo)) continue;
        sel.push(futuro);
      }
      escolha = [nivel, rot, sel];
      if (sel.length >= nMin) break;
    }

    const [nivel, rot, sel] = escolha;
    const n = sel.length;
    const v = sel.filter(x => x === 0).length;
    const p = n ? v / n : null;
    if (n < nMin) avisos.push('amostra fina: n=' + n + ' mesmo no degrau mais largo');
    return {
      ok: n > 0,
      periodo,
      instante: [tempoAtual, t],
      placar_rel: [gfVivo, gzVivo],
      fav: pfavVivo === null ? null : {
        lado: favVivo === 0 ? 'casa' : 'fora',
        p: Math.round(pfavVivo * 10000) / 10000,
        odd_justa: Math.round(1 / pfavVivo * 1000) / 1000,
      },
      p, n, green: v,
      ic95: n ? wilson(v, n) : null,
      justa: p ? 1 / p : null,
      nivel, filtros: rot,
      dist: { '0': v, '1': sel.filter(x => x === 1).length, '2+': sel.filter(x => x >= 2).length },
      avisos, ignorados,
    };
  }

  // ------------------------------------------------------------------
  // Integração com o Scanner do site Futebol. scanRodar chama
  // Motor1.scanner(scLinhas, tabela) depois de montar a tabela; as linhas
  // da tabela estão na mesma ordem de scLinhas (a 1ª <tr> é o cabeçalho).
  let pendente = null, falhou = null;

  function fmt(x) {
    if (x === null || x === undefined || !isFinite(x)) return '—';
    return (typeof raiz.fmtOdd === 'function') ? raiz.fmtOdd(x) : x.toFixed(2);
  }
  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'); }

  function scanner(linhas, tabela) {
    pendente = { linhas, tabela };
    const trs = tabela.querySelectorAll('tr');
    if (!trs.length) return;
    if (!trs[0].querySelector('.m1h'))
      trs[0].insertAdjacentHTML('beforeend', '<th class="m1h">Motor 1</th><th class="m1h">M1 base</th>');

    linhas.forEach(({ j, r }, i) => {
      const tr = trs[i + 1];
      if (!tr) return;
      tr.querySelectorAll('.m1c').forEach(td => td.remove());
      let c1, c2;
      if (falhou) { c1 = '—'; c2 = '<span class="nota">base histórica não carregou</span>'; }
      else if (!jogos) { c1 = '…'; c2 = '<span class="nota">carregando base histórica</span>'; }
      else {
        const m = consulta(j, r.periodo);
        if (!m.ok) { c1 = '—'; c2 = esc(m.motivo || 'sem jogos parecidos'); }
        else {
          const delta = r.justa ? (m.justa / r.justa - 1) * 100 : null;
          const [lo, hi] = m.ic95;
          c1 = '<b>' + fmt(m.justa) + '</b>'
            + (delta === null ? '' : ' <span class="fonte">(' + (delta >= 0 ? '+' : '') + delta.toFixed(0) + '%)</span>')
            + '<br><span class="fonte">n=' + m.n + ' · ' + (m.p * 100).toFixed(1) + '%</span>';
          const alerta = m.avisos.length ? ' <span style="color:var(--amarelo)" title="' + esc(m.avisos.join(' | ')) + '">⚠</span>' : '';
          c2 = '<span class="fonte">' + esc(m.filtros) + '<br>IC ' + fmt(1 / hi) + '–' + fmt(lo > 0 ? 1 / lo : Infinity) + '</span>' + alerta;
          tr.title = 'Motor 1: placar ' + m.placar_rel.join('x') + ' (fav x zebra)'
            + (m.fav ? ' · fav ' + m.fav.lado + ' justa ' + m.fav.odd_justa : '')
            + ' · mais gols: 0=' + m.dist['0'] + ' 1=' + m.dist['1'] + ' 2+=' + m.dist['2+']
            + (m.ignorados.length ? ' · sem base: ' + m.ignorados.map(s => s.split(':')[0]).join(', ') : '');
        }
      }
      tr.insertAdjacentHTML('beforeend', '<td class="m1c">' + c1 + '</td><td class="m1c">' + c2 + '</td>');
    });
  }

  function carregar(url) {
    return fetch(url).then(r => {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(doc => {
      carregarDoc(doc);
      if (pendente) scanner(pendente.linhas, pendente.tabela);
    }).catch(e => {
      falhou = e;
      if (pendente) scanner(pendente.linhas, pendente.tabela);
      if (raiz.console) console.warn('Motor 1: base histórica não carregou', e);
    });
  }

  raiz.Motor1 = {
    consulta, carregarDoc, carregar, scanner,
    carregado: () => jogos !== null,
    _interno: { instante, estado, decodifica, tolerancia, wilson, semMargem, rotulo, ESCADA, N_MIN },
  };

  // no navegador: carrega a base ao lado deste arquivo
  if (typeof document !== 'undefined' && document.currentScript && typeof fetch === 'function')
    carregar(new URL('linha_do_tempo.json', document.currentScript.src).href);
})(typeof window !== 'undefined' ? window : globalThis);
