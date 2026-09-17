Attribute VB_Name = "Utilities"
Public Function IsWorkbookOpened(bookName As String)
    Dim wb As Workbook
    IsWorkbookOpened = False
    
    For Each wb In Application.Workbooks
        If wb.Name = bookName Then
            IsWorkbookOpened = True
            Exit For
        End If
    Next

End Function


Public Function ColumnNumberToLetter(ColNum As Integer) As String
    Dim ColLetter As String
    Dim remainder As Long
    Dim colNumber As Integer
    colNumber = ColNum
    Do While colNumber > 0
        remainder = (colNumber - 1) Mod 26
        ColLetter = Chr(65 + remainder) & ColLetter
        colNumber = Int((colNumber - 1) / 26)
    Loop
    
    ColumnNumberToLetter = ColLetter
End Function

Public Function CountBetween(data As Variant, Condition1 As Double, Condition2 As Double) As Long
    Dim i As Long
    Dim count As Long
    
    ' 初始化计数器
    count = 0
    
    ' 遍历数组中的每个元素
    For i = LBound(data) To UBound(data)
        ' 检查当前元素是否在两个条件之间
        If data(i) > Condition1 And data(i) <= Condition2 Then
            count = count + 1
        End If
    Next i
    
    ' 返回符合条件的元素数量
    CountBetween = count
End Function

Public Function 转换()
    Application.ScreenUpdating = False
    pth = ThisWorkbook.Path & ""
    flnm = Dir(pth & "*.csv")
    flnm = Application.GetOpenFilename("Excel 文件 ,*.csv")
    With Workbooks.Open(flnm, ReadOnly:=True)
        .SaveAs Replace(flnm, ".csv", ""), IIf(Application.Version >= 12, xlWorkbookDefault, xlWorkbookNormal)
        .Close
    End With
End Function


Public Function SaveWorkbookAsXlsxInCurrentPath()
    Dim wb As Workbook
    Dim currentPath As String
    Dim newFileName As String
    Dim filePath As String
    
    ' 获取当前活动的工作簿
    Set wb = ActiveWorkbook
    
    ' 如果工作簿从未保存过，这会引发错误，因此先检查是否已保存
    If wb.Path = "" Then
        MsgBox "当前工作簿尚未保存，请先保存工作簿以确定其位置。", vbExclamation
        Exit Function
    End If
    
    ' 获取当前工作簿的路径
    currentPath = wb.Path
    
    ' 定义新的文件名称 (这里假设你想要保留原文件名但更改扩展名)
    ' 请注意，如果你不想覆盖原始文件，你需要修改文件名
    newFileName = Left(wb.Name, InStrRev(wb.Name, ".") - 1) & "Marked.xlsx"
    
    ' 构建完整的文件路径
    filePath = currentPath & Application.PathSeparator & newFileName
    
    ' 保存工作簿为 .xlsx 格式
    wb.SaveAs FileName:=filePath, FileFormat:=xlOpenXMLWorkbook

    ' 提示用户保存完成
    MsgBox "工作簿已成功保存为：" & filePath
End Function

