/* Helpers de CPF/CNPJ. Validacao e formatacao espelhando o backend.
 *
 * Carregado ANTES de app.js (app.js usa validateCPF/CNPJ e formatDocument
 * em varios pontos do form de criacao de nota).
 *
 * Exposicao via window.Economart.documents.* (namespace) + aliases globais
 * (window.validateCPF, etc.) para compat com callers historicos.
 *
 * Refator P2-1 v2 (auditoria). Funcoes movidas do app.js sem alterar
 * comportamento — apenas reorganizacao. */
(function () {
  'use strict';

  window.Economart = window.Economart || {};
  window.Economart.documents = window.Economart.documents || {};

  function stripDocDigits(value) {
    return (value || '').replace(/\D/g, '');
  }

  function validateCPF(cpf) {
    cpf = stripDocDigits(cpf);
    if (cpf.length !== 11 || /^(\d)\1+$/.test(cpf)) return false;
    let s = 0;
    for (let i = 0; i < 9; i++) s += parseInt(cpf[i]) * (10 - i);
    let r = s % 11;
    const dv1 = r < 2 ? 0 : 11 - r;
    if (dv1 !== parseInt(cpf[9])) return false;
    s = 0;
    for (let i = 0; i < 10; i++) s += parseInt(cpf[i]) * (11 - i);
    r = s % 11;
    const dv2 = r < 2 ? 0 : 11 - r;
    return dv2 === parseInt(cpf[10]);
  }

  function validateCNPJ(cnpj) {
    cnpj = stripDocDigits(cnpj);
    if (cnpj.length !== 14 || /^(\d)\1+$/.test(cnpj)) return false;
    const w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
    const w2 = [6].concat(w1);
    let s = 0;
    for (let i = 0; i < 12; i++) s += parseInt(cnpj[i]) * w1[i];
    let r = s % 11;
    const dv1 = r < 2 ? 0 : 11 - r;
    if (dv1 !== parseInt(cnpj[12])) return false;
    s = 0;
    for (let i = 0; i < 13; i++) s += parseInt(cnpj[i]) * w2[i];
    r = s % 11;
    const dv2 = r < 2 ? 0 : 11 - r;
    return dv2 === parseInt(cnpj[13]);
  }

  function formatDocument(digits) {
    digits = stripDocDigits(digits);
    if (digits.length === 11) {
      return `${digits.slice(0, 3)}.${digits.slice(3, 6)}.${digits.slice(6, 9)}-${digits.slice(9)}`;
    }
    if (digits.length === 14) {
      return `${digits.slice(0, 2)}.${digits.slice(2, 5)}.${digits.slice(5, 8)}/${digits.slice(8, 12)}-${digits.slice(12)}`;
    }
    return digits;
  }

  // Namespace canonico.
  window.Economart.documents.stripDocDigits = stripDocDigits;
  window.Economart.documents.validateCPF = validateCPF;
  window.Economart.documents.validateCNPJ = validateCNPJ;
  window.Economart.documents.formatDocument = formatDocument;

  // Aliases globais para compatibilidade.
  window.stripDocDigits = stripDocDigits;
  window.validateCPF = validateCPF;
  window.validateCNPJ = validateCNPJ;
  window.formatDocument = formatDocument;
})();
