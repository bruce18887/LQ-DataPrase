Attribute VB_Name = "AutoMark"
Public Type ConfigInfo
     EnableAutoDataDistribution As Boolean
     EnableAutoForzen As Boolean
     EnableAutoFilter As Boolean
     EnableAutoHideColumns As Boolean
     EnableAutoCopyMarkedFile As Boolean
End Type

Public g_DataParser As New DataParser
Public g_Config As ConfigInfo
Public IsPorcess As Boolean

Sub OpenDataFileAndMark()
    Application.ScreenUpdating = False
    
    Dim FullFileName As String
    Dim FileName As String

    FullFileName = Application.GetOpenFilename("Excel File ,*.csv")
    If FullFileName = "False" Then
        MsgBox "No file selected!"
        Exit Sub
    Else
        File = Split(FullFileName, "\")
        FileName = File(UBound(File))     'The last element of the array is filename
        If IsWorkbookOpened(FileName) Then
            MsgBox "You have opened" & FileName & "!" & vbCrLf & "You might want to try [CallAutoMarkConfigPanel] or close this file and Run again!"
            Exit Sub
        End If
    End If

    Workbooks.Open (FullFileName)
    
    
    CallAutoMarkConfigPanel
    
    Application.ScreenUpdating = True
End Sub

Private Sub On_ImportButtonClick()
    g_DataParser.ImportButton_Changed
End Sub

Private Sub On_ComboxChanged()
    g_DataParser.ComboBox_Changed
End Sub

Sub CallAutoMarkConfigPanel()
Attribute CallAutoMarkConfigPanel.VB_ProcData.VB_Invoke_Func = "Q\n14"
    With UserForm1
        ' 计算并设置位置
        .Left = (Application.UsableWidth - .Width) / 2
        .Top = (Application.UsableHeight - .Height) / 2

        ' 显示UserForm
        .Show
    End With
    
    If IsPorcess = True Then
        g_DataParser.ProcessDataAndMarkFailuresConfigRun g_Config
    End If
    
End Sub
